import SwiftUI

struct DiagnosticsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Agent Status
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        diagRow("Desired State", value: model.helperDesiredState.capitalized, color: model.helperDesiredState == "enabled" ? .green : .orange)
                        diagRow("Last Seen", value: model.helperLastSeenAt?.formatted() ?? "Never")
                        diagRow("Last Error", value: model.helperLastError.isEmpty ? "None" : model.helperLastError, color: model.helperLastError.isEmpty ? nil : .red)
                    }
                } label: {
                    HStack {
                        Label("Background Agent", systemImage: "bolt.circle")
                            .font(.headline)
                        Spacer()
                        Button(action: { Task { await model.refreshAll() } }) {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                }

                // Backend
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        diagRow("URL", value: model.store.backendURL.absoluteString)
                        diagRow("Health", value: model.health?.status.capitalized ?? "Unknown", color: healthColor)
                        diagRow("Mac Status", value: model.state.mac_status?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown", color: macStatusColor)
                        diagRow("Mac Reason", value: model.state.mac_status_reason ?? "Waiting for helper")
                        if let build = model.health?.build {
                            diagRow("Build", value: [build.build_version, build.git_sha?.prefix(7).map(String.init)].compactMap { $0 }.joined(separator: " / "))
                        }
                        if let uptime = model.health?.uptime_seconds {
                            diagRow("Uptime", value: formatUptime(uptime))
                        }
                        if let db = model.health?.database {
                            diagRow("Database", value: db.ok == true ? "OK" : (db.error ?? "Unknown"), color: db.ok == true ? .green : .red)
                        }
                        if let errors = model.health?.startup_errors, !errors.isEmpty {
                            diagRow("Startup Errors", value: errors.joined(separator: "; "), color: .red)
                        }
                    }
                } label: {
                    Label("Backend", systemImage: "server.rack")
                        .font(.headline)
                }

                // Calendar
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        diagRow("Calendar Target", value: CalendarSyncEngine.shared.targetDescription())
                        if let cal = model.health?.calendar {
                            diagRow("Pending Jobs", value: "\(cal.pending_jobs ?? 0)")
                            if let executor = cal.executor {
                                diagRow("Executor", value: executor)
                            }
                        }
                    }
                } label: {
                    Label("Calendar Sync", systemImage: "calendar.badge.clock")
                        .font(.headline)
                }

                // Hint
                GroupBox {
                    Text("If the Mac shows offline, open Life Manager and tap Repair Agent in the Tracking tab. If the backend is unreachable, check your URL and auth in ~/.config/life-manager/.")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                } label: {
                    Label("Troubleshooting", systemImage: "questionmark.circle")
                        .font(.headline)
                }
            }
            .padding(24)
        }
    }

    private func diagRow(_ label: String, value: String, color: Color? = nil) -> some View {
        LabeledContent(label) {
            Text(value)
                .foregroundStyle(color ?? .primary)
                .lineLimit(2)
                .multilineTextAlignment(.trailing)
        }
    }

    private var healthColor: Color? {
        switch model.health?.status {
        case "ok": return .green
        case "degraded": return .orange
        default: return .red
        }
    }

    private var macStatusColor: Color? {
        switch model.state.mac_status {
        case "online": return .green
        case "online_idle": return .green
        case "paused": return .orange
        case "degraded": return .orange
        case "offline": return .red
        default: return nil
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
