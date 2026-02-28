import SwiftUI

struct OverviewView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                LabeledContent("Backend") {
                    Text(model.health?.status.capitalized ?? "Unknown")
                }
                LabeledContent("Mac Status") {
                    Text(model.state.mac_status?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown")
                }
                LabeledContent("Mac Detail") {
                    Text(model.state.mac_status_reason ?? "Waiting for helper state")
                }
                LabeledContent("Last Heartbeat") {
                    Text(ageString(model.state.last_mac_heartbeat_age_seconds))
                }
                LabeledContent("Last Telemetry") {
                    Text(ageString(model.state.last_mac_snapshot_age_seconds))
                }
                LabeledContent("Current Activity") {
                    Text(model.state.current_activity_summary ?? model.state.current_activity_category ?? "Unknown")
                }
                LabeledContent("Current iPhone Location") {
                    Text(model.state.current_location ?? "No recent location")
                }
                if LegacyConfigImporter.isLegacyPythonAgentRunning() {
                    Text("Python agent is still active. Disable it after native parity is confirmed.")
                        .foregroundStyle(.orange)
                }

                Divider()

                VStack(alignment: .leading, spacing: 8) {
                    Text("Recent Chat")
                        .font(.headline)
                    if model.chatTurns.isEmpty {
                        Text("No recent chat.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(Array(model.chatTurns.suffix(4).reversed()), id: \.self) { turn in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(turn.time).font(.caption).foregroundStyle(.secondary)
                                Text("You: \(turn.user)")
                                Text("Life Manager: \(turn.reply)")
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.bottom, 6)
                        }
                    }
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
}
