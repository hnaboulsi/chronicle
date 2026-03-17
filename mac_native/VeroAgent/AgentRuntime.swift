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
    private var captureTask: Task<Void, Never>?
    private var presenceTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var isRunning = false
    private var consecutiveHeartbeatFailures = 0

    private var localPresenceState = "active"
    private var localScreenState = "visible"
    private var localPresenceChangedAt = Date()
    private var lastPostedPresenceKey = ""
    private var systemSleeping = false
    private var sessionLocked = false
    private var observers: [NSObjectProtocol] = []

    // Window-change tracking: any app/tab switch resets the effective idle clock
    private var lastCapturedWindowKey = ""
    private var lastWindowChangedAt = Date.distantPast

    func start() {
        guard !isRunning else { return }
        isRunning = true
        notifier.requestAuthorizationIfNeeded()
        registerSystemObservers()
        heartbeatTask = Task { await runHeartbeatLoop() }
        captureTask = Task { await runCaptureLoop() }
        presenceTask = Task { await runPresenceLoop() }
        refreshTask = Task { await runRefreshLoop() }
    }

    func stop() {
        isRunning = false
        heartbeatTask?.cancel()
        captureTask?.cancel()
        presenceTask?.cancel()
        refreshTask?.cancel()
        heartbeatTask = nil
        captureTask = nil
        presenceTask = nil
        refreshTask = nil
        unregisterSystemObservers()
    }

    private func registerSystemObservers() {
        guard observers.isEmpty else { return }

        let workspaceCenter = NSWorkspace.shared.notificationCenter
        observers.append(
            workspaceCenter.addObserver(
                forName: NSWorkspace.willSleepNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleSleepTransition(isSleeping: true) }
            }
        )
        observers.append(
            workspaceCenter.addObserver(
                forName: NSWorkspace.didWakeNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleSleepTransition(isSleeping: false) }
            }
        )
        observers.append(
            workspaceCenter.addObserver(
                forName: NSWorkspace.screensDidSleepNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleScreenLock(isLocked: true) }
            }
        )
        observers.append(
            workspaceCenter.addObserver(
                forName: NSWorkspace.screensDidWakeNotification,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleScreenLock(isLocked: false) }
            }
        )

        let distributed = DistributedNotificationCenter.default()
        observers.append(
            distributed.addObserver(
                forName: Notification.Name("com.apple.screenIsLocked"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleScreenLock(isLocked: true) }
            }
        )
        observers.append(
            distributed.addObserver(
                forName: Notification.Name("com.apple.screenIsUnlocked"),
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { await self?.handleScreenLock(isLocked: false) }
            }
        )
    }

    private func unregisterSystemObservers() {
        let workspaceCenter = NSWorkspace.shared.notificationCenter
        let distributed = DistributedNotificationCenter.default()
        for observer in observers {
            workspaceCenter.removeObserver(observer)
            distributed.removeObserver(observer)
        }
        observers.removeAll()
    }

    private func runHeartbeatLoop() async {
        while !Task.isCancelled {
            await sendHeartbeat()
            try? await Task.sleep(for: .seconds(60))
        }
    }

    private func runCaptureLoop() async {
        while !Task.isCancelled {
            if shouldCapture {
                await sendTelemetry()
            }
            let seconds = Double(max(60, store.captureInterval))
            try? await Task.sleep(for: .seconds(seconds))
        }
    }

    private func runPresenceLoop() async {
        while !Task.isCancelled {
            if shouldCapture {
                await sendPresenceIfNeeded()
            }
            try? await Task.sleep(for: .seconds(15))
        }
    }

    private func runRefreshLoop() async {
        while !Task.isCancelled {
            await refreshBackendState()
            if store.calendarSyncEnabled {
                await CalendarSyncEngine.shared.syncPendingJobs(client: backend)
            }
            try? await Task.sleep(for: .seconds(60))
        }
    }

    private var shouldCapture: Bool {
        store.isConfigured && store.helperDesiredState != "disabled" && store.trackingEnabled
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
        if store.calendarSyncEnabled {
            let status = CalendarSyncEngine.shared.authorizationStatus()
            if status == .denied || status == .restricted {
                return "missing_calendar"
            }
        }
        return "ok"
    }

    private func handleSleepTransition(isSleeping: Bool) async {
        systemSleeping = isSleeping
        updateLocalPresenceState(forceTimestamp: Date())
        await sendPresenceIfNeeded(force: true)
    }

    private func handleScreenLock(isLocked: Bool) async {
        sessionLocked = isLocked
        updateLocalPresenceState(forceTimestamp: Date())
        await sendPresenceIfNeeded(force: true)
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
            consecutiveHeartbeatFailures = 0
            store.helperLastError = ""
            if wasFailingBefore {
                notifier.deliver(kind: .callout, title: "Vero", body: "Connection to backend restored.")
            }
            if let serverTracking = response.tracking_enabled {
                store.trackingEnabled = serverTracking
            }
            if let interval = response.capture_interval_seconds, interval >= 60 {
                store.captureInterval = interval
            }
        } catch {
            consecutiveHeartbeatFailures += 1
            store.helperLastError = error.localizedDescription
            if consecutiveHeartbeatFailures == 3 {
                notifier.deliver(
                    kind: .callout,
                    title: "Vero",
                    body: "The menu bar companion has not reached the backend for several minutes."
                )
            }
        }
    }

    private func sendPresenceIfNeeded(force: Bool = false) async {
        guard store.isConfigured else { return }
        let snapshot = currentPresenceSnapshot()
        let key = "\(snapshot.presenceState)|\(snapshot.screenState)"
        guard force || key != lastPostedPresenceKey else { return }

        do {
            try await backend.sendPresence(
                presenceState: snapshot.presenceState,
                screenState: snapshot.screenState,
                changedAt: snapshot.changedAt,
                idleTimeSeconds: snapshot.idleTimeSeconds
            )
            lastPostedPresenceKey = key
            store.helperLastSeenAt = Date()
            if !store.helperLastError.isEmpty {
                store.helperLastError = ""
            }
        } catch {
            store.helperLastError = error.localizedDescription
        }
    }

    private func sendTelemetry() async {
        guard store.isConfigured else { return }

        let snapshot = captureSnapshot()
        do {
            let response = try await backend.sendTelemetry(
                appName: snapshot.appName,
                windowTitle: snapshot.windowTitle,
                idleTimeSeconds: snapshot.idleTimeSeconds,
                presenceState: snapshot.presenceState,
                screenState: snapshot.screenState,
                detailedCaptureEnabled: store.privacyMode == "detailed",
                secondsSinceWindowChange: snapshot.secondsSinceWindowChange
            )
            store.helperLastSeenAt = Date()
            if !store.helperLastError.isEmpty {
                store.helperLastError = ""
            }
            if let prompt = response.prompt, !prompt.isEmpty {
                notifier.deliver(kind: .callout, title: "Vero", body: prompt)
            }
        } catch {
            store.helperLastError = error.localizedDescription
        }
    }

    private func refreshBackendState() async {
        guard store.isConfigured else { return }

        do {
            let state = try await backend.fetchState()
            if let interval = state.capture_interval_seconds, interval >= 60 {
                store.captureInterval = interval
            }

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

    private func currentPresenceSnapshot() -> PresenceSnapshot {
        updateLocalPresenceState()
        return PresenceSnapshot(
            presenceState: localPresenceState,
            screenState: localScreenState,
            idleTimeSeconds: currentIdleTime(),
            changedAt: localPresenceChangedAt
        )
    }

    private func updateLocalPresenceState(forceTimestamp: Date? = nil) {
        let idleSeconds = currentIdleTime()
        let nextScreenState: String
        if systemSleeping {
            nextScreenState = "sleeping"
        } else if sessionLocked {
            nextScreenState = "locked"
        } else {
            nextScreenState = "visible"
        }

        let nextPresenceState: String
        switch nextScreenState {
        case "sleeping":
            nextPresenceState = "sleeping"
        case "locked":
            nextPresenceState = "locked"
        default:
            if idleSeconds < 300 {
                nextPresenceState = "active"
            } else if idleSeconds < 1800 {
                nextPresenceState = "idle"
            } else {
                nextPresenceState = "away"
            }
        }

        if nextPresenceState != localPresenceState || nextScreenState != localScreenState || forceTimestamp != nil {
            localPresenceChangedAt = forceTimestamp ?? Date()
            localPresenceState = nextPresenceState
            localScreenState = nextScreenState
        }
    }

    private func currentIdleTime() -> Int {
        Int(CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .null))
    }

    private func captureSnapshot() -> TelemetrySnapshot {
        let app = NSWorkspace.shared.frontmostApplication
        let appName = app?.localizedName ?? "Unknown"
        let bundleID = app?.bundleIdentifier ?? ""
        let presence = currentPresenceSnapshot()
        let title = browserTabTitle(forBundleIdentifier: bundleID) ?? focusedWindowTitle() ?? appName

        // Track window changes: any app/tab switch is evidence the user is present
        let windowKey = "\(appName)|\(title)"
        if windowKey != lastCapturedWindowKey {
            lastWindowChangedAt = Date()
            lastCapturedWindowKey = windowKey
        }
        let secondsSinceWindowChange = Int(Date().timeIntervalSince(lastWindowChangedAt))

        // Effective idle = min of actual idle time and time since last window change.
        // If the user switched tabs 2 minutes ago, effective idle is 120s not 1800s.
        let effectiveIdleSeconds = min(presence.idleTimeSeconds, secondsSinceWindowChange)

        return TelemetrySnapshot(
            appName: appName,
            windowTitle: title,
            idleTimeSeconds: effectiveIdleSeconds,
            presenceState: presence.presenceState,
            screenState: presence.screenState,
            secondsSinceWindowChange: secondsSinceWindowChange
        )
    }

    private func asAXUIElement(_ ref: CFTypeRef) -> AXUIElement? {
        guard CFGetTypeID(ref) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(ref, to: AXUIElement.self)
    }

    private func focusedWindowTitle() -> String? {
        let systemWide = AXUIElementCreateSystemWide()
        var focusedApp: CFTypeRef?
        let appResult = AXUIElementCopyAttributeValue(systemWide, kAXFocusedApplicationAttribute as CFString, &focusedApp)
        guard appResult == .success, let rawApp = focusedApp, let appElement = asAXUIElement(rawApp) else {
            return nil
        }

        var focusedWindow: CFTypeRef?
        let windowResult = AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedWindow)
        guard windowResult == .success, let rawWindow = focusedWindow, let windowElement = asAXUIElement(rawWindow) else {
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
        store.browserTabsAttempted = true
        if let err = error {
            let code = (err[NSAppleScript.errorNumber] as? Int) ?? 0
            if code == -1743 {
                store.browserTabsGranted = false
            }
            return nil
        }
        store.browserTabsGranted = true
        let value = output.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }
}

private struct PresenceSnapshot {
    let presenceState: String
    let screenState: String
    let idleTimeSeconds: Int
    let changedAt: Date
}

private struct TelemetrySnapshot {
    let appName: String
    let windowTitle: String
    let idleTimeSeconds: Int
    let presenceState: String
    let screenState: String
    let secondsSinceWindowChange: Int
}
