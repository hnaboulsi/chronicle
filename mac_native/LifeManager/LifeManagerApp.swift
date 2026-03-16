import SwiftUI

@main
struct LifeManagerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = NativeAppModel()
    @State private var requiresSetup: Bool

    init() {
        let store = AppGroupStore.shared
        store.clearInvalidConfiguration()
        _requiresSetup = State(initialValue: !store.isConfigured)
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if requiresSetup {
                    SetupView {
                        requiresSetup = false
                    }
                    .frame(minWidth: 560, minHeight: 680)
                } else {
                    RootView()
                        .environmentObject(model)
                        .frame(minWidth: 520, minHeight: 560)
                        .task {
                            await model.startup()
                        }
                        .onOpenURL { url in
                            model.handle(url: url)
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
