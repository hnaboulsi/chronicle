import AppKit
import ApplicationServices
import Combine
import Foundation
import SwiftUI

@MainActor
final class NativeAppModel: ObservableObject {
    // Only permissions + agent state (no dashboard data)
    @Published var permissionSnapshot = PermissionSnapshot(accessibility: "pending", notifications: "pending", calendar: "pending", appleEvents: "pending")
    @Published var helperDesiredState: String = AppGroupStore.shared.helperDesiredState
    @Published var helperActualStatus: String = "unknown"
    @Published var helperLastSeenAt: Date? = AppGroupStore.shared.helperLastSeenAt
    @Published var helperLastError: String = AppGroupStore.shared.helperLastError
    @Published var statusMessage = ""

    let store = AppGroupStore.shared
    private var refreshTimer: AnyCancellable?
    private var didStart = false

    func startup() async {
        guard !didStart else { return }
        didStart = true
        AgentNotificationManager.shared.requestAuthorizationIfNeeded()

        // Capture initial permissions
        permissionSnapshot = await PermissionSnapshot.capture()
        await updateAgentState()

        // Poll agent state every 5 seconds
        refreshTimer = Timer.publish(every: 5, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                Task { [weak self] in
                    await self?.updateAgentState()
                }
            }
    }

    private func updateAgentState() async {
        permissionSnapshot = await PermissionSnapshot.capture()
        helperDesiredState = store.helperDesiredState
        helperActualStatus = HelperController.shared.actualStatus
        helperLastSeenAt = store.helperLastSeenAt
        helperLastError = store.helperLastError
    }

    func enableHelper() {
        HelperController.shared.ensureHelperEnabled()
        helperDesiredState = store.helperDesiredState
        statusMessage = "Background agent enabled."
    }

    func disableHelper() {
        HelperController.shared.disableHelper()
        helperDesiredState = store.helperDesiredState
        statusMessage = "Background agent disabled."
    }

    func repairHelper() {
        HelperController.shared.repairHelper()
        helperDesiredState = store.helperDesiredState
        statusMessage = "Background agent re-registered."
    }

    func openWebDashboard() {
        if let baseURL = store.backendURL {
            let url = baseURL.appendingPathComponent("dashboard/index.html")
            NSWorkspace.shared.open(url)
        } else {
            statusMessage = BackendError.notConfigured.localizedDescription
        }
    }

    func openSystemSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    func requestAccessibilityPermission() {
        AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as NSDictionary)
        Task {
            try? await Task.sleep(for: .seconds(1))
            permissionSnapshot = await PermissionSnapshot.capture()
        }
    }

    func requestAppleEventsPermission() {
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) {
            let script = """
            tell application "Google Chrome"
                if (count of windows) = 0 then return ""
                return title of active tab of front window
            end tell
            """
            var error: NSDictionary?
            if let appleScript = NSAppleScript(source: script) {
                let _ = appleScript.executeAndReturnError(&error)
                AppGroupStore.shared.browserTabsAttempted = true
                if error == nil {
                    AppGroupStore.shared.browserTabsGranted = true
                }
            }
        }

        Task {
            try? await Task.sleep(for: .seconds(2))
            permissionSnapshot = await PermissionSnapshot.capture()
        }
    }
}
