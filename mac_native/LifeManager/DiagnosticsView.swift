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
                HStack {
                    Text("Actual Status")
                    Spacer()
                    StatusBadge(
                        label: model.helperActualStatus.capitalized,
                        color: model.helperActualStatus == "running" ? .green : .orange
                    )
                }
                if model.helperActualStatus == "needs approval" {
                    Link("Open Login Items", destination: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_LoginItems")!)
                        .foregroundStyle(.blue)
                }
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
                Text("The background agent runs as a login item and sends heartbeats every 60 seconds.")
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
                if model.helperActualStatus != "running" {
                    Button(action: { model.repairHelper() }) {
                        Label("Repair", systemImage: "wrench.and.screwdriver")
                    }
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
}
