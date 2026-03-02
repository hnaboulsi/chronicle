import SwiftUI

@main
struct VeroApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = NativeAppModel()
    @State private var requiresSetup: Bool

    init() {
        LegacyConfigImporter.migrateAppGroupIfNeeded()
        let store = AppGroupStore.shared
        store.clearInvalidConfiguration()
        _requiresSetup = State(initialValue: !store.isConfigured)
    }

    var body: some Scene {
        Window("Vero", id: "main") {
            Group {
                if requiresSetup {
                    SetupView {
                        requiresSetup = false
                    }
                    .frame(minWidth: 600, minHeight: 700)
                } else {
                    LiteMainView()
                        .environmentObject(model)
                        .frame(width: 500, height: 600)
                        .task {
                            await model.startup()
                        }
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
                let store = AppGroupStore.shared
                store.clearInvalidConfiguration()
                if !store.isConfigured {
                    requiresSetup = true
                }
            }
        }
        .windowStyle(.hiddenTitleBar)
    }
}

struct LiteMainView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(spacing: Spacing.sm) {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "waveform.path.ecg")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(.indigo)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Vero")
                            .font(.headline)
                        Text("Agent Dashboard")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Circle()
                        .fill(model.helperLastError.isEmpty ? Color.green : Color.red)
                        .frame(width: 10, height: 10)
                }
                .padding(Spacing.lg)

                Divider()

                // Open Dashboard Button
                Button(action: { model.openWebDashboard() }) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "globe")
                        Text("Open Web Dashboard")
                        Spacer()
                        Image(systemName: "arrow.up.right")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(Spacing.md)
                    .background(Color.indigo.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .padding(Spacing.lg)

                Divider()
            }
            .background(Color(.controlBackgroundColor))

            // Permissions View
            PermissionsView()
                .environmentObject(model)

            Spacer()

            // Status Message
            if !model.statusMessage.isEmpty {
                Text(model.statusMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(Spacing.md)
            }
        }
    }
}
