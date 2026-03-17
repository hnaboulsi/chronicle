import AppKit
import ServiceManagement

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let runtime = AgentRuntime()
    private let statusItemController = StatusItemController()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let store = AppGroupStore.shared
        store.clearInvalidConfiguration()

        let result = LegacyConfigImporter.importIfNeeded()
        if result.legacyPythonRunning {
            LegacyConfigImporter.killLegacyPythonAgent()
            store.helperLastError = "Legacy Python menu bar agent was detected and stopped. Remove the old login item from System Settings > General > Login Items."

            if !store.legacyPythonWarningShown {
                store.legacyPythonWarningShown = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    let alert = NSAlert()
                    alert.messageText = "Legacy Python Agent Stopped"
                    alert.informativeText = "The old Python-based Vero menu bar/login item was detected and stopped. Remove it from System Settings > General > Login Items so it does not relaunch."
                    alert.alertStyle = .warning
                    alert.addButton(withTitle: "OK")
                    alert.runModal()
                }
            }
        }

        // Start the menu bar icon and telemetry loops.
        statusItemController.start(appDelegate: self)
        runtime.start()

        // Unregister the old VeroAgent login item (stale from the two-process era).
        // This clears the BTM entry so macOS stops trying to launch the removed helper.
        if #available(macOS 13.0, *) {
            let staleAgent = SMAppService.loginItem(identifier: AppConstants.agentBundleIdentifier)
            try? staleAgent.unregister()
        }

        // Register as a login item so Vero auto-starts on login.
        if #available(macOS 13.0, *) {
            try? SMAppService.mainApp.register()
        }

        if !store.isConfigured {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                self.openSettingsWindow()
            }
        }
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        runtime.stop()
        statusItemController.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false  // Menu bar app — window close must NOT kill the process
    }

    func openSettingsWindow() {
        if NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil) {
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        if NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil) {
            NSApp.activate(ignoringOtherApps: true)
        }
    }
}
