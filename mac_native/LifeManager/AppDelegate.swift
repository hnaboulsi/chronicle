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
                    alert.informativeText = "The old Python-based Vero menu bar/login item was detected and stopped. Remove it from System Settings > General > Login Items so it does not relaunch."
                    alert.alertStyle = .warning
                    alert.addButton(withTitle: "OK")
                    alert.runModal()
                }
            }
        }

        // Always repair (unregister + re-register) the login item on startup.
        // After each fresh build the ad-hoc code signature changes, causing a
        // Launch Constraint Violation when launchd tries to relaunch the old binary.
        // repairHelper() refreshes the SMAppService registration to the new binary.
        HelperController.shared.repairHelper()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
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
