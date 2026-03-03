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
                        .frame(width: 520)
                        .frame(maxHeight: .infinity)
                        .background(Color.panelBg)
                        .ignoresSafeArea()
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
            .onOpenURL { _ in
                NSApplication.shared.windows.forEach { $0.makeKeyAndOrderFront(nil) }
                NSApplication.shared.activate(ignoringOtherApps: true)
            }
        }
        .windowStyle(.hiddenTitleBar)
    }
}

struct LiteMainView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            LiteHeaderBar()
                .environmentObject(model)
            LiteDashboardButton()
                .environmentObject(model)
            PermissionsView()
                .environmentObject(model)
        }
        .background(Color.appBg)
    }
}

// MARK: - Header Bar

private struct LiteHeaderBar: View {
    @EnvironmentObject private var model: NativeAppModel

    private var isConnected: Bool { model.helperLastError.isEmpty }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Color.brandAccent)

            VStack(alignment: .leading, spacing: 1) {
                Text("Vero")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color.textPrimary)
                Text("Agent Dashboard")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundStyle(Color.textMuted)
            }

            Spacer()

            Circle()
                .fill(isConnected ? Color.statusGreen : Color.statusRed)
                .frame(width: 8, height: 8)
                .shadow(color: isConnected ? Color.statusGreen.opacity(0.5) : Color.clear, radius: 3)
        }
        .padding(.horizontal, 20)
        .frame(height: 56)
        .background(Color.panelBg)
        .overlay(alignment: .bottom) {
            Color.borderSubtle.frame(height: 1)
        }
    }
}

// MARK: - Dashboard Button Row

private struct LiteDashboardButton: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var isHovering = false

    var body: some View {
        Button(action: { model.openWebDashboard() }) {
            HStack(spacing: 12) {
                Image(systemName: "globe")
                    .font(.system(size: 14, weight: .regular))
                    .foregroundStyle(Color.textSecondary)
                Text("Open Web Dashboard")
                    .font(.system(size: 13, weight: .regular))
                    .foregroundStyle(Color.textPrimary)
                Spacer()
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundStyle(Color.textMuted)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 13)
            .background(isHovering ? Color.surfaceHover : Color.surface)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(.easeInOut(duration: 0.1)) { isHovering = h } }
        .overlay(alignment: .bottom) {
            Color.borderSubtle.frame(height: 1)
        }
    }
}
