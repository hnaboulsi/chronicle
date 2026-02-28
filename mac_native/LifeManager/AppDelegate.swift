import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        let result = LegacyConfigImporter.importIfNeeded()
        if result.legacyPythonRunning {
            AppGroupStore.shared.helperLastError = "Legacy Python agent still appears to be running."
        }
        HelperController.shared.ensureHelperEnabled()
    }
}
