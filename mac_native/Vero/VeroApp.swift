import SwiftUI

@main
struct VeroApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    init() {
        LegacyConfigImporter.migrateAppGroupIfNeeded()
        let store = AppGroupStore.shared
        store.clearInvalidConfiguration()
    }

    var body: some Scene {
        Settings {
            SetupView(onConnected: {})
                .frame(minWidth: 480, minHeight: 280)
        }
    }
}
