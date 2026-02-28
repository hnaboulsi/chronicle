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
        Window("Vero", id: "main") {
            Group {
                if requiresSetup {
                    SetupView {
                        requiresSetup = false
                    }
                    .frame(minWidth: 600, minHeight: 700)
                } else {
                    RootView()
                        .environmentObject(model)
                        .frame(minWidth: 980, minHeight: 700)
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
