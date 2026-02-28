import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

@MainActor
final class AgentRuntime {
    static let shared = AgentRuntime()

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
            try? await Task.sleep(for: .seconds(60))
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
        if !AXIsProcessTrusted() {
            return "missing_accessibility"
        }
        let status = CalendarSyncEngine.shared.authorizationStatus()
        if status == .denied || status == .restricted {
            return "missing_calendar"
        }
        return "ok"
    }

    private func sendHeartbeat() async {
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
            consecutiveHeartbeatFailures = 0
            // Sync tracking state from backend (e.g. user toggled via web dashboard)
            if let serverTracking = response.tracking_enabled {
                store.trackingEnabled = serverTracking
            }
        } catch {
            consecutiveHeartbeatFailures += 1
            store.helperLastError = error.localizedDescription
            // Only notify after 3+ consecutive failures to avoid spam during brief outages
            if consecutiveHeartbeatFailures >= 3 {
                notifier.deliver(
                    kind: .callout,
                    title: "Life Manager Agent",
                    body: "The background agent has not reached the backend for several minutes."
                )
            }
        }
    }

    private func sendTelemetry() async {
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
                notifier.deliver(kind: .callout, title: "Life Manager", body: prompt)
            }
        } catch {
            store.helperLastError = error.localizedDescription
        }
    }

    private func refreshBackendState() async {
        do {
            _ = try await backend.fetchState()

            let callout = try? await backend.fetchCallout()
            if let calloutText = callout?.callout, !calloutText.isEmpty {
                notifier.deliver(kind: .callout, title: "Stay On Track", body: calloutText)
            }

            let checkin = try? await backend.fetchCheckin()
            if let checkinText = checkin?.checkin, !checkinText.isEmpty {
                notifier.deliver(kind: .checkin, title: "Life Manager Check-in", body: checkinText)
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

    private func focusedWindowTitle() -> String? {
        let systemWide = AXUIElementCreateSystemWide()
        var focusedApp: CFTypeRef?
        let appResult = AXUIElementCopyAttributeValue(systemWide, kAXFocusedApplicationAttribute as CFString, &focusedApp)
        guard appResult == .success,
              let appElement = focusedApp.map({ unsafeBitCast($0, to: AXUIElement.self) }) else {
            return nil
        }

        var focusedWindow: CFTypeRef?
        let windowResult = AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedWindow)
        guard windowResult == .success,
              let windowElement = focusedWindow.map({ unsafeBitCast($0, to: AXUIElement.self) }) else {
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
        case "com.google.Chrome":
            return runAppleScript("""
            tell application "Google Chrome"
                if (count of windows) = 0 then return ""
                return title of active tab of front window
            end tell
            """)
        case "com.brave.Browser":
            return runAppleScript("""
            tell application "Brave Browser"
                if (count of windows) = 0 then return ""
                return title of active tab of front window
            end tell
            """)
        case "company.thebrowser.Browser":
            return runAppleScript("""
            tell application "Arc"
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
        if error != nil {
            return nil
        }
        let value = output.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }
}

private struct TelemetrySnapshot {
    let appName: String
    let windowTitle: String
    let idleTimeSeconds: Int
}
