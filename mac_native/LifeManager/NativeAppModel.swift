import AppKit
import ApplicationServices
import Combine
import Foundation
import SwiftUI

enum AppScreen: String, CaseIterable, Identifiable {
    case overview
    case tracking
    case zones
    case permissions
    case diagnostics
    case calendar
    case iphone
    case chat

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview:
            return "Overview"
        case .tracking:
            return "Tracking"
        case .zones:
            return "Zones"
        case .permissions:
            return "Permissions"
        case .diagnostics:
            return "Diagnostics"
        case .calendar:
            return "Calendar"
        case .iphone:
            return "iPhone Setup"
        case .chat:
            return "Chat"
        }
    }
}

@MainActor
final class NativeAppModel: ObservableObject {
    @Published var selectedScreen: AppScreen = .overview
    @Published var state = DashboardState()
    @Published var settings = BackendSettings(
        polling_interval_seconds: 60,
        tracking_enabled: true,
        backend_mode: "railway_primary",
        ai_provider: "auto",
        llm_mode: "balanced",
        hourly_summaries_enabled: true,
        classification_interval_seconds: 300,
        llm_daily_cap: 200,
        user_timezone: TimeZone.current.identifier
    )
    @Published var zones: [ZoneRecord] = []
    @Published var calendarJobs: [CalendarJob] = []
    @Published var chatTurns: [ChatTurn] = []
    @Published var health: HealthResponse?
    @Published var permissionSnapshot = PermissionSnapshot(accessibility: "pending", notifications: "pending", calendar: "pending", appleEvents: "pending")
    @Published var statusMessage = ""
    @Published var notificationLevel = AppGroupStore.shared.notificationLevel
    @Published var lastSavedSettings = BackendSettings(
        polling_interval_seconds: 60,
        tracking_enabled: true,
        backend_mode: "railway_primary",
        ai_provider: "auto",
        llm_mode: "balanced",
        hourly_summaries_enabled: true,
        classification_interval_seconds: 300,
        llm_daily_cap: 200,
        user_timezone: TimeZone.current.identifier
    )
    @Published var lastSavedNotificationLevel = AppGroupStore.shared.notificationLevel

    // Diagnostic props (reactive, refreshed from AppGroupStore on each cycle)
    @Published var helperDesiredState: String = AppGroupStore.shared.helperDesiredState
    @Published var helperActualStatus: String = "unknown"
    @Published var helperLastSeenAt: Date? = AppGroupStore.shared.helperLastSeenAt
    @Published var helperLastError: String = AppGroupStore.shared.helperLastError

    let backend = BackendClient.shared
    let store = AppGroupStore.shared

    private var refreshTimer: AnyCancellable?
    private var didStart = false

    func startup() async {
        guard !didStart else { return }
        didStart = true
        AgentNotificationManager.shared.requestAuthorizationIfNeeded()
        await refreshAll()
        // Auto-refresh every 30 seconds so the UI stays current
        refreshTimer = Timer.publish(every: 30, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                Task { [weak self] in
                    await self?.refreshAll()
                }
            }
    }

    func refreshAll() async {
        do {
            async let stateTask = backend.fetchState()
            async let settingsTask = backend.fetchSettings()
            async let zonesTask = backend.fetchZones()
            async let jobsTask = backend.fetchCalendarJobs()
            async let chatTask = backend.fetchChatHistory()
            async let healthTask = backend.fetchHealth()
            async let permissionsTask = PermissionSnapshot.capture()

            state = try await stateTask
            settings = try await settingsTask
            zones = try await zonesTask
            calendarJobs = try await jobsTask
            chatTurns = try await chatTask
            health = try await healthTask
            permissionSnapshot = await permissionsTask

            store.trackingEnabled = settings.tracking_enabled
            store.aiProvider = settings.ai_provider
            store.pollingInterval = settings.polling_interval_seconds
            store.classificationInterval = settings.classification_interval_seconds
            lastSavedSettings = settings
            lastSavedNotificationLevel = notificationLevel

            // Sync diagnostic props from AppGroupStore and HelperController
            helperDesiredState = store.helperDesiredState
            helperActualStatus = HelperController.shared.actualStatus
            helperLastSeenAt = store.helperLastSeenAt
            helperLastError = store.helperLastError

            statusMessage = ""
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    func saveSettings() async {
        do {
            try await backend.saveSettings(settings)
            store.trackingEnabled = settings.tracking_enabled
            store.aiProvider = settings.ai_provider
            store.pollingInterval = settings.polling_interval_seconds
            store.classificationInterval = settings.classification_interval_seconds
            store.notificationLevel = notificationLevel
            lastSavedSettings = settings
            lastSavedNotificationLevel = notificationLevel
            statusMessage = "Saved."
            await refreshAll()
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    @discardableResult
    func save(zone: ZoneRecord) async -> Bool {
        do {
            try await backend.save(zone: zone)
            statusMessage = "Saved."
            await refreshAll()
            return true
        } catch {
            statusMessage = error.localizedDescription
            return false
        }
    }

    @discardableResult
    func delete(zone: ZoneRecord) async -> Bool {
        do {
            try await backend.delete(zone: zone)
            statusMessage = "Deleted."
            await refreshAll()
            return true
        } catch {
            statusMessage = error.localizedDescription
            return false
        }
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
        if let target = state.backend_target_url, let url = URL(string: target + "/dashboard/index.html") {
            NSWorkspace.shared.open(url)
        } else if let baseURL = store.backendURL {
            let url = baseURL.appendingPathComponent("dashboard/index.html")
            NSWorkspace.shared.open(url)
        } else {
            statusMessage = BackendError.notConfigured.localizedDescription
        }
    }

    func sendReply(_ text: String) async {
        do {
            try await backend.sendChat(text)
            await refreshAll()
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    func clearActivityLogs(minutes: Int?) async {
        do {
            let count = try await backend.clearLogs(minutes: minutes)
            statusMessage = "Cleared \(count) log\(count == 1 ? "" : "s")."
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    func openSystemSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    func requestAccessibilityPermission() {
        // Registers the current binary with macOS TCC and shows a prompt if not trusted.
        // Must be called from the running process — simply toggling in System Settings
        // doesn't re-register a new binary after rebuilds.
        AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as NSDictionary)
        Task {
            try? await Task.sleep(for: .seconds(1))
            permissionSnapshot = await PermissionSnapshot.capture()
        }
    }

    func handle(url: URL) {
        switch url.host?.lowercased() {
        case "repair":
            selectedScreen = .diagnostics
        case "zones":
            selectedScreen = .zones
        default:
            selectedScreen = .overview
        }
        NSApplication.shared.activate(ignoringOtherApps: true)
        statusMessage = "Opened via \(url.absoluteString)"
    }
}
