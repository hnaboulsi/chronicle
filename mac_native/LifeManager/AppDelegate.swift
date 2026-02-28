import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        let store = AppGroupStore.shared
        store.clearInvalidConfiguration()

        let result = LegacyConfigImporter.importIfNeeded()

        // Kill any running legacy Python processes
        if result.legacyPythonRunning {
            LegacyConfigImporter.killLegacyPythonAgent()
            store.helperLastError = "Legacy Python menu bar agent was detected and stopped. Remove the old login item from System Settings > General > Login Items."

            if !store.legacyPythonWarningShown {
                store.legacyPythonWarningShown = true

                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    let alert = NSAlert()
                    alert.messageText = "Legacy Python Agent Stopped"
                    alert.informativeText = "The old Python-based Life Manager menu bar/login item was detected and stopped. Remove it from System Settings > General > Login Items so it does not relaunch."
                    alert.alertStyle = .warning
                    alert.addButton(withTitle: "OK")
                    alert.runModal()
                }
            }
        }

        HelperController.shared.ensureHelperEnabled()
    }

    func applicationShouldTerminateWhenLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            for window in sender.windows {
                window.makeKeyAndOrderFront(nil)
            }
        }
        return true
    }
}
