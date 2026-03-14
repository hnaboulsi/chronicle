import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

@MainActor
final class AgentRuntime {
    private let backend = BackendClient.shared
    private let store = AppGroupStore.shared
    private let notifier = AgentNotificationManager.shared

    private var heartbeatTask: Task<Void, Never>?
    private var telemetryTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var isRunning = false
    private var consecutiveHeartbeatFailures = 0

    func start() {
        guard !isRunning else { return }
        isRunning = true
        notifier.requestAuthorizationIfNeeded()
        // Accessibility permission prompts are handled by the main app
        heartbeatTask = Task { await runHeartbeatLoop() }
        telemetryTask = Task { await runTelemetryLoop() }
        refreshTask = Task { await runRefreshLoop() }
    }

    func stop() {
        isRunning = false
        heartbeatTask?.cancel()
        telemetryTask?.cancel()
        refreshTask?.cancel()
        heartbeatTask = nil
        telemetryTask = nil
        refreshTask = nil
    }

    private func runHeartbeatLoop() async {
        while !Task.isCancelled {
            await sendHeartbeat()
            let delay = heartbeatDelay()
            try? await Task.sleep(for: .seconds(delay))
        }
    }

    /// Returns the next heartbeat interval with exponential backoff on failures.
    /// 0 failures → 60s, 1 failure → 120s, 2+ failures → 300s.
    private func heartbeatDelay() -> Double {
        switch consecutiveHeartbeatFailures {
        case 0: return 60
        case 1: return 120
        default: return 300
        }
    }

    private func runTelemetryLoop() async {
        while !Task.isCancelled {
            if shouldSendTelemetry {
                await sendTelemetry()
            }
            let seconds = max(60, store.pollingInterval)
            try? await Task.sleep(for: .seconds(Double(seconds)))
        }
    }

    private func runRefreshLoop() async {
        while !Task.isCancelled {
            await refreshBackendState()
            await CalendarSyncEngine.shared.syncPendingJobs(client: backend)
            try? await Task.sleep(for: .seconds(60))
        }
    }

    private var shouldSendTelemetry: Bool {
        store.helperDesiredState != "disabled" && store.trackingEnabled
    }

    private var currentAgentState: String {
        if store.helperDesiredState == "disabled" || !store.trackingEnabled {
            return "paused"
        }
        let permissions = currentPermissionsState
        return permissions == "ok" ? "running" : "degraded"
    }

    private var currentPermissionsState: String {
        // Accessibility is best-effort for window titles; not required for core tracking.
        // The agent will still try to read window titles but silently falls back to app names.
        let status = CalendarSyncEngine.shared.authorizationStatus()
        if status == .denied || status == .restricted {
            return "missing_calendar"
        }
        return "ok"
    }

    private func sendHeartbeat() async {
        guard store.isConfigured else {
            if !store.helperLastError.isEmpty {
                store.helperLastError = ""
            }
            return
        }

        let wasFailingBefore = consecutiveHeartbeatFailures >= 3

        do {
            let response = try await backend.sendHeartbeat(
                clientID: store.clientID,
                appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev",
                agentState: currentAgentState,
                trackingEnabled: store.trackingEnabled,
                permissionsState: currentPermissionsState,
                lastError: store.helperLastError
            )
            store.helperLastSeenAt = Date()
            // Notify once when backend connection is restored after a failure streak.
            if wasFailingBefore {
                notifier.deliver(
                    kind: .callout,
                    title: "Vero",
                    body: "Connection to backend restored."
                )
            }
            consecutiveHeartbeatFailures = 0
            store.helperLastError = ""
            // Sync tracking state from backend (e.g. user toggled via web dashboard)
            if let serverTracking = response.tracking_enabled {
                store.trackingEnabled = serverTracking
            }
        } catch {
            consecutiveHeartbeatFailures += 1
            store.helperLastError = error.localizedDescription
            // Only notify after 3+ consecutive failures to avoid spam during brief outages
            if consecutiveHeartbeatFailures == 3 {
                notifier.deliver(
                    kind: .callout,
                    title: "Vero",
                    body: "The background agent has not reached the backend for several minutes."
                )
            }
        }
    }

    private func sendTelemetry() async {
        guard store.isConfigured else {
            return
        }

        let snapshot = captureSnapshot()
        do {
            let response = try await backend.sendTelemetry(
                appName: snapshot.appName,
                windowTitle: snapshot.windowTitle,
                idleTimeSeconds: snapshot.idleTimeSeconds
            )
            store.helperLastSeenAt = Date()
            if !store.helperLastError.isEmpty {
                store.helperLastError = ""
            }
            // Show backend prompts (idle alerts, focus nudges)
            if let prompt = response.prompt, !prompt.isEmpty {
                notifier.deliver(kind: .callout, title: "Vero", body: prompt)
            }
        } catch {
            store.helperLastError = error.localizedDescription
        }
    }

    private func refreshBackendState() async {
        guard store.isConfigured else {
            return
        }

        do {
            _ = try await backend.fetchState()

            let callout = try? await backend.fetchCallout()
            if let calloutText = callout?.callout, !calloutText.isEmpty {
                notifier.deliver(kind: .callout, title: "Stay On Track", body: calloutText)
            }

            let checkin = try? await backend.fetchCheckin()
            if let checkinText = checkin?.checkin, !checkinText.isEmpty {
                notifier.deliver(kind: .checkin, title: "Vero", body: checkinText)
            }
        } catch {
            store.helperLastError = error.localizedDescription
        }
    }

    private func captureSnapshot() -> TelemetrySnapshot {
        let app = NSWorkspace.shared.frontmostApplication
        let appName = app?.localizedName ?? "Unknown"
        let bundleID = app?.bundleIdentifier ?? ""
        let idleTime = Int(CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .null))
        let title = browserTabTitle(forBundleIdentifier: bundleID) ?? focusedWindowTitle() ?? appName
        return TelemetrySnapshot(appName: appName, windowTitle: title, idleTimeSeconds: idleTime)
    }

    /// Safely cast a CFTypeRef to AXUIElement after validating its type ID.
    private func asAXUIElement(_ ref: CFTypeRef) -> AXUIElement? {
        guard CFGetTypeID(ref) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(ref, to: AXUIElement.self)
    }

    private func focusedWindowTitle() -> String? {
        let systemWide = AXUIElementCreateSystemWide()
        var focusedApp: CFTypeRef?
        let appResult = AXUIElementCopyAttributeValue(systemWide, kAXFocusedApplicationAttribute as CFString, &focusedApp)
        guard appResult == .success,
              let raw = focusedApp,
              let appElement = asAXUIElement(raw) else {
            return nil
        }

        var focusedWindow: CFTypeRef?
        let windowResult = AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedWindow)
        guard windowResult == .success,
              let rawWindow = focusedWindow,
              let windowElement = asAXUIElement(rawWindow) else {
            return nil
        }

        var titleValue: CFTypeRef?
        let titleResult = AXUIElementCopyAttributeValue(windowElement, kAXTitleAttribute as CFString, &titleValue)
        guard titleResult == .success, let title = titleValue as? String else {
            return nil
        }
        return title.isEmpty ? nil : title
    }

    private func browserTabTitle(forBundleIdentifier bundleIdentifier: String) -> String? {
        switch bundleIdentifier {
        case "com.apple.Safari":
            return runAppleScript("""
            tell application "Safari"
                if (count of windows) = 0 then return ""
                return name of current tab of front window
            end tell
            """)
        case "com.google.Chrome", "com.brave.Browser", "company.thebrowser.Browser":
            // For Chrome, Brave, and Arc: try AppleScript with short timeout
            // Note: Requires user to have granted Chrome/Brave/Arc scripting access
            // Fall back to Accessibility API which may show window title instead of tab title
            let browserName = bundleIdentifier == "com.google.Chrome" ? "Google Chrome" :
                             bundleIdentifier == "com.brave.Browser" ? "Brave Browser" : "Arc"
            return runAppleScript("""
            tell application "\(browserName)"
                if (count of windows) = 0 then return ""
                return title of active tab of front window
            end tell
            """)
        default:
            return nil
        }
    }

    private func runAppleScript(_ source: String) -> String? {
        var error: NSDictionary?
        guard let script = NSAppleScript(source: source) else { return nil }
        let output = script.executeAndReturnError(&error)
        // Mark that we have attempted Apple Events at least once.
        store.browserTabsAttempted = true
        if let err = error {
            let code = (err[NSAppleScript.errorNumber] as? Int) ?? 0
            // Error -1743: not authorized to send Apple events
            if code == -1743 {
                store.browserTabsGranted = false
            }
            return nil
        }
        // Success — permission is granted
        store.browserTabsGranted = true
        let value = output.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }
}

private struct TelemetrySnapshot {
    let appName: String
    let windowTitle: String
    let idleTimeSeconds: Int
}
