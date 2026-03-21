import AppKit
import ApplicationServices
import Foundation

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let store = AppGroupStore.shared
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()

    private let statusMenuItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let errorMenuItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private lazy var toggleTrackingItem = NSMenuItem(title: "", action: #selector(toggleTracking), keyEquivalent: "")
    private lazy var openDashboardItem = NSMenuItem(title: "Open Dashboard", action: #selector(openDashboard), keyEquivalent: "")
    private lazy var settingsItem = NSMenuItem(title: "Connection Settings…", action: #selector(openSettings), keyEquivalent: ",")
    private lazy var accessibilityItem = NSMenuItem(title: "Request Accessibility Access", action: #selector(requestAccessibilityAccess), keyEquivalent: "")
    private lazy var calendarItem = NSMenuItem(title: "Request Calendar Access", action: #selector(requestCalendarAccess), keyEquivalent: "")
    private lazy var systemSettingsItem = NSMenuItem(title: "Open Privacy Settings", action: #selector(openSystemSettings), keyEquivalent: "")
    private lazy var quitItem = NSMenuItem(title: "Quit Vero", action: #selector(quitApp), keyEquivalent: "q")

    private weak var appDelegate: AppDelegate?

    func start(appDelegate: AppDelegate? = nil) {
        self.appDelegate = appDelegate

        if let button = statusItem.button {
            let config = NSImage.SymbolConfiguration(pointSize: 15, weight: .semibold)
            let image = NSImage(systemSymbolName: "waveform.path.ecg", accessibilityDescription: "Vero")
            image?.isTemplate = true
            button.image = image?.withSymbolConfiguration(config)
        }

        menu.delegate = self
        rebuildMenu()
        statusItem.menu = menu
        refreshMenu()
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        refreshMenu()
    }

    func stop() {
        NSStatusBar.system.removeStatusItem(statusItem)
    }

    private func rebuildMenu() {
        [toggleTrackingItem, openDashboardItem, settingsItem, accessibilityItem, calendarItem, systemSettingsItem, quitItem]
            .forEach { $0.target = self }
        errorMenuItem.isEnabled = false
        statusMenuItem.isEnabled = false

        menu.removeAllItems()
        menu.addItem(statusMenuItem)
        menu.addItem(errorMenuItem)
        menu.addItem(.separator())
        menu.addItem(toggleTrackingItem)
        menu.addItem(openDashboardItem)
        menu.addItem(settingsItem)
        menu.addItem(.separator())
        menu.addItem(accessibilityItem)
        menu.addItem(calendarItem)
        menu.addItem(systemSettingsItem)
        menu.addItem(.separator())
        menu.addItem(quitItem)
    }

    private func refreshMenu() {
        let isConfigured = store.isConfigured
        let hasError = !store.helperLastError.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let trackingEnabled = store.trackingEnabled && store.helperDesiredState != "disabled"

        let statusText: String
        if !isConfigured {
            statusText = "Status: Connect Vero to start"
        } else if hasError {
            statusText = "Status: Attention needed"
        } else if trackingEnabled {
            statusText = "Status: Menu bar companion active"
        } else {
            statusText = "Status: Paused"
        }

        statusMenuItem.title = statusText
        errorMenuItem.title = hasError ? "Last error: \(store.helperLastError)" : ""
        errorMenuItem.isHidden = !hasError

        toggleTrackingItem.title = trackingEnabled ? "Pause Tracking" : "Resume Tracking"
        toggleTrackingItem.isEnabled = isConfigured
        openDashboardItem.isEnabled = isConfigured
        settingsItem.title = hasError ? "Repair Vero…" : (isConfigured ? "Connection Settings…" : "Connect Vero…")
        statusItem.button?.toolTip = "Vero"
    }

    @objc private func toggleTracking() {
        let newState = !store.trackingEnabled
        store.trackingEnabled = newState
        store.helperDesiredState = newState ? "enabled" : "disabled"
        refreshMenu()
    }

    @objc private func openDashboard() {
        guard let baseURL = store.backendURL else { return }
        NSWorkspace.shared.open(baseURL.appendingPathComponent("today"))
    }

    @objc private func openSettings() {
        appDelegate?.openSettingsWindow()
    }

    @objc private func requestAccessibilityAccess() {
        AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": true] as NSDictionary)
    }

    @objc private func requestCalendarAccess() {
        Task {
            await CalendarSyncEngine.shared.requestAccessIfNeeded()
        }
    }

    @objc private func openSystemSettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else {
            return
        }
        NSWorkspace.shared.open(url)
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
