import SwiftUI

struct OverviewView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Status at a glance
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Circle()
                                .fill(statusDotColor)
                                .frame(width: 10, height: 10)
                            LabeledContent("Backend") {
                                Text(model.health?.status.capitalized ?? "Unknown")
                            }
                        }
                        LabeledContent("Mac Status") {
                            Text(model.state.mac_status?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown")
                                .foregroundStyle(macStatusColor)
                        }
                        LabeledContent("Mac Detail") {
                            Text(model.state.mac_status_reason ?? "Waiting for helper state")
                                .foregroundStyle(.secondary)
                        }
                        LabeledContent("Last Heartbeat") {
                            Text(ageString(model.state.last_mac_heartbeat_age_seconds))
                        }
                        LabeledContent("Last Telemetry") {
                            Text(ageString(model.state.last_mac_snapshot_age_seconds))
                        }
                    }
                } label: {
                    Label("System", systemImage: "waveform.path.ecg")
                        .font(.headline)
                }

                // Activity
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        LabeledContent("Current Activity") {
                            Text(model.state.current_activity_summary ?? model.state.current_activity_category ?? "Unknown")
                        }
                        LabeledContent("iPhone Location") {
                            Text(model.state.current_location ?? "No recent location")
                                .foregroundStyle(.secondary)
                        }
                        LabeledContent("Sleep Status") {
                            Text(model.state.sleep_status_note ?? "Unknown")
                                .foregroundStyle(.secondary)
                        }
                    }
                } label: {
                    Label("Activity", systemImage: "figure.walk")
                        .font(.headline)
                }

                // Connected to
                GroupBox {
                    LabeledContent("Server") {
                        Text(model.store.backendURL.absoluteString)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                } label: {
                    Label("Connection", systemImage: "network")
                        .font(.headline)
                }

                // Recent Chat
                GroupBox {
                    if model.chatTurns.isEmpty {
                        Text("No recent chat.")
                            .foregroundStyle(.secondary)
                    } else {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(model.chatTurns.suffix(4).reversed()), id: \.self) { turn in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(turn.time)
                                        .font(.caption)
                                        .foregroundStyle(.tertiary)
                                    Text("You: \(turn.user)")
                                        .font(.callout)
                                    Text("Agent: \(turn.reply)")
                                        .font(.callout)
                                        .foregroundStyle(.secondary)
                                }
                                if turn != model.chatTurns.suffix(4).reversed().last {
                                    Divider()
                                }
                            }
                        }
                    }
                } label: {
                    Label("Recent Chat", systemImage: "bubble.left.and.bubble.right")
                        .font(.headline)
                }
            }
            .padding(24)
        }
    }

    private func ageString(_ value: Int?) -> String {
        guard let value else { return "Unknown" }
        if value < 60 { return "\(value)s ago" }
        return "\(value / 60)m ago"
    }

    private var statusDotColor: Color {
        switch model.health?.status {
        case "ok": return .green
        case "degraded": return .orange
        default: return .red
        }
    }

    private var macStatusColor: Color {
        switch model.state.mac_status {
        case "online", "online_idle": return .green
        case "paused", "degraded": return .orange
        case "offline": return .red
        default: return .secondary
        }
    }
}
