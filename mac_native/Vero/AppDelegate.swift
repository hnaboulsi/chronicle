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
        let agentBundleID = "com.naboulsi.vero.agent"
        let alreadyRunning = NSRunningApplication.runningApplications(withBundleIdentifier: agentBundleID).count > 0
        
        if !alreadyRunning {
            HelperController.shared.repairHelper()
        }

        // Kick off the agent immediately — don't wait for next login/launchd cycle.
        // Guard against launching a duplicate if SMAppService already started the agent.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            let stillRunning = NSRunningApplication.runningApplications(withBundleIdentifier: agentBundleID).count > 0
            guard !stillRunning else { return }
            let agentURL = Bundle.main.bundleURL
                .appendingPathComponent("Contents/Library/LoginItems/VeroAgent.app")
            guard FileManager.default.fileExists(atPath: agentURL.path) else { return }
            NSWorkspace.shared.openApplication(
                at: agentURL,
                configuration: NSWorkspace.OpenConfiguration()
            )
        }

        // Match window background to the app's dark theme so no gray shows through.
        DispatchQueue.main.async {
            NSApplication.shared.windows.forEach {
                $0.backgroundColor = NSColor(red: 0.078, green: 0.078, blue: 0.094, alpha: 1)
                $0.titlebarAppearsTransparent = true
            }
        }
    }

    func applicationWillTerminate(_ aNotification: Notification) {
        let agentBundleID = "com.naboulsi.vero.agent"
        let applications = NSRunningApplication.runningApplications(withBundleIdentifier: agentBundleID)
        applications.forEach { $0.terminate() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false // Just close window, keep both apps alive
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
