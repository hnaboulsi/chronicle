import SwiftUI

struct DiagnosticsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            Section {
                HStack {
                    Text("Desired State")
                    Spacer()
                    StatusBadge(
                        label: model.helperDesiredState.capitalized,
                        color: model.helperDesiredState == "enabled" ? .green : .orange
                    )
                }
                InfoRow(label: "Presence", value: presenceLabel(model.state.presence_state))
                InfoRow(label: "Last Heartbeat", value: ageString(model.state.last_mac_heartbeat_age_seconds))
                InfoRow(label: "Last Capture", value: ageString(model.state.last_mac_capture_age_seconds))
                InfoRow(label: "Last Seen", value: model.helperLastSeenAt?.formatted() ?? "Never")
                if !model.helperLastError.isEmpty {
                    HStack {
                        Text("Last Error")
                            .foregroundStyle(.red)
                        Spacer()
                        Text(model.helperLastError)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .multilineTextAlignment(.trailing)
                    }
                }
            } header: {
                Text("Background Agent")
            } footer: {
                Text("The helper runs as a login item. Heartbeats stay at 60 seconds, while captures use your selected interval.")
            }

            Section {
                CopyableInfoRow(
                    label: "Server",
                    value: model.store.backendURL?.absoluteString ?? "Not configured",
                    mono: true
                )
                HStack {
                    Text("Health")
                    Spacer()
                    StatusBadge(
                        label: model.health?.status.capitalized ?? "Unknown",
                        color: healthColor(model.health?.status)
                    )
                }
                HStack {
                    Text("Mac Status")
                    Spacer()
                    StatusBadge(
                        label: (model.state.mac_status ?? "unknown").replacingOccurrences(of: "_", with: " ").capitalized,
                        color: macStatusColor(model.state.mac_status)
                    )
                }
                InfoRow(label: "Detail", value: model.state.mac_status_reason ?? "Waiting for agent")
                InfoRow(label: "Screen State", value: (model.state.screen_state ?? "unknown").capitalized)
                InfoRow(label: "Privacy Mode", value: (model.state.privacy_mode ?? "private") == "detailed" ? "Detailed Capture" : "Private by Default")

                if let build = model.health?.build {
                    let buildStr = [build.build_version, build.git_sha.map { String($0.prefix(7)) }]
                        .compactMap { $0 }
                        .joined(separator: " / ")
                    CopyableInfoRow(label: "Build", value: buildStr, mono: true)
                }

                if let uptime = model.health?.uptime_seconds {
                    InfoRow(label: "Uptime", value: formatUptime(uptime))
                }

                if let db = model.health?.database {
                    HStack {
                        Text("Database")
                        Spacer()
                        StatusBadge(
                            label: db.ok == true ? "OK" : "Error",
                            color: db.ok == true ? .green : .red
                        )
                    }
                    if let error = db.error, !error.isEmpty {
                        InfoRow(label: "Error", value: error, color: .red)
                    }
                }
            }

            if let errors = model.health?.startup_errors, !errors.isEmpty {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(errors, id: \.self) { error in
                            HStack(spacing: 8) {
                                Image(systemName: "exclamationmark.circle.fill")
                                    .foregroundStyle(.red)
                                    .font(.system(size: 12))
                                Text(error)
                                    .font(.caption)
                                    .foregroundStyle(.red)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("Startup Errors")
                }
            }

            Section {
                InfoRow(label: "Target", value: CalendarSyncEngine.shared.targetDescription())
                HStack {
                    Text("Enabled")
                    Spacer()
                    StatusBadge(
                        label: model.settings.calendar_sync_enabled ? "On" : "Off",
                        color: model.settings.calendar_sync_enabled ? .green : .orange
                    )
                }
                if let cal = model.health?.calendar {
                    InfoRow(label: "Pending Jobs", value: "\(cal.pending_jobs ?? 0)")
                    if let executor = cal.executor {
                        InfoRow(label: "Executor", value: executor, mono: true)
                    }
                }
            } header: {
                Text("Calendar Sync")
            } footer: {
                Text("Manages syncing of your productive sessions to Apple Calendar.")
            }

            Section {
                Link("Open Accessibility Settings", destination: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                Link("Open Notifications Settings", destination: URL(string: "x-apple.systempreferences:com.apple.preference.notifications")!)
                Button("Open Tracking Screen") {
                    model.selectedScreen = .tracking
                }
            } header: {
                Text("Troubleshooting")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Diagnostics")
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button(action: { model.repairHelper() }) {
                    Label("Repair", systemImage: "wrench.and.screwdriver")
                }
            }
        }
    }

    private func formatUptime(_ seconds: Int) -> String {
        let hours = seconds / 3600
        let minutes = (seconds % 3600) / 60
        if hours > 0 {
            return "\(hours)h \(minutes)m"
        }
        return "\(minutes)m"
    }

    private func ageString(_ value: Int?) -> String {
        guard let value else { return "Unknown" }
        if value < 60 { return "\(value)s ago" }
        if value < 3600 { return "\(value / 60)m ago" }
        if value < 86_400 { return "\(value / 3600)h ago" }
        return "\(value / 86_400)d ago"
    }

    private func presenceLabel(_ value: String?) -> String {
        switch (value ?? "").lowercased() {
        case "active":
            return "Active"
        case "idle":
            return "Idle"
        case "away":
            return "Away"
        case "locked":
            return "Locked"
        case "sleeping":
            return "Sleeping"
        default:
            return "Unknown"
        }
    }
}
