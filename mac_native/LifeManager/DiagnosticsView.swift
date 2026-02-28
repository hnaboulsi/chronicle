import SwiftUI

struct DiagnosticsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            LabeledContent("Helper Desired State") {
                Text(AppGroupStore.shared.helperDesiredState.capitalized)
            }
            LabeledContent("Helper Last Seen") {
                Text(AppGroupStore.shared.helperLastSeenAt?.formatted() ?? "Unknown")
            }
            LabeledContent("Helper Last Error") {
                Text(AppGroupStore.shared.helperLastError.isEmpty ? "None" : AppGroupStore.shared.helperLastError)
            }
            LabeledContent("Backend Health") {
                Text(model.health?.status.capitalized ?? "Unknown")
            }
            LabeledContent("Mac Status") {
                Text(model.state.mac_status?.capitalized ?? "Unknown")
            }
            LabeledContent("Legacy Python Agent") {
                Text(LegacyConfigImporter.isLegacyPythonAgentRunning() ? "Detected" : "Not Detected")
            }
            Spacer()
        }
        .padding(24)
    }
}
