import AppKit

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let store = AppGroupStore.shared
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()

    private var summaryItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var lastSeenItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var openSetupItem = NSMenuItem(title: "", action: #selector(openApp), keyEquivalent: "")
    private var openDashboardItem = NSMenuItem(title: "Open Dashboard", action: #selector(openDashboard), keyEquivalent: "")
    private var openSettingsItem = NSMenuItem(title: "Open System Settings", action: #selector(openSystemSettings), keyEquivalent: "")
    private var toggleTrackingItem = NSMenuItem(title: "", action: #selector(toggleTracking), keyEquivalent: "")
    private var quitItem = NSMenuItem(title: "Quit Helper", action: #selector(quitHelper), keyEquivalent: "")

    func start() {
        if let button = statusItem.button {
            let config = NSImage.SymbolConfiguration(pointSize: 15, weight: .semibold)
            let image = NSImage(systemSymbolName: "waveform.path.ecg", accessibilityDescription: "Vero")
            image?.isTemplate = true
            button.image = image?.withSymbolConfiguration(config)
            button.toolTip = "Vero"
        }

        menu.delegate = self
        rebuildMenu()
        statusItem.menu = menu
    }

    func stop() {
        statusItem.menu = nil
        NSStatusBar.system.removeStatusItem(statusItem)
    }

    func menuWillOpen(_ menu: NSMenu) {
        rebuildMenu()
    }

    private func rebuildMenu() {
        summaryItem.title = currentSummary
        summaryItem.isEnabled = false

        lastSeenItem.title = currentLastSeenLabel
        lastSeenItem.isEnabled = false

        openDashboardItem.target = self
        openDashboardItem.isEnabled = store.backendConfiguration != nil

        openSetupItem.target = self
        openSetupItem.title = menuBarActionTitle

        openSettingsItem.target = self

        toggleTrackingItem.title = store.trackingEnabled ? "Pause Tracking" : "Resume Tracking"
        toggleTrackingItem.target = self
        toggleTrackingItem.isEnabled = store.backendConfiguration != nil

        quitItem.target = self

        menu.removeAllItems()
        menu.addItem(summaryItem)
        menu.addItem(lastSeenItem)
        menu.addItem(.separator())
        menu.addItem(openDashboardItem)
        if shouldShowSetupAction {
            menu.addItem(openSetupItem)
        }
        menu.addItem(openSettingsItem)
        menu.addItem(toggleTrackingItem)
        menu.addItem(.separator())
        menu.addItem(quitItem)
    }

    private var currentSummary: String {
        if let configuration = store.backendConfiguration {
            let host = configuration.baseURL.host ?? configuration.baseURL.absoluteString
            if !store.helperLastError.isEmpty {
                return "Needs attention • \(host)"
            }
            return store.trackingEnabled ? "Menu bar companion connected • \(host)" : "Tracking paused • \(host)"
        }
        return "Connect Vero to start the menu bar companion"
    }

    private var currentLastSeenLabel: String {
        guard let lastSeen = store.helperLastSeenAt else {
            return "Last seen: Never"
        }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return "Last seen: \(formatter.localizedString(for: lastSeen, relativeTo: Date()))"
    }

    @objc
    private func openApp() {
        guard let url = URL(string: "\(AppConstants.urlScheme)://open") else {
            return
        }
        NSWorkspace.shared.open(url)
    }

    @objc
    private func openDashboard() {
        guard let configuration = store.backendConfiguration else {
            return
        }
        let url = configuration.baseURL.appendingPathComponent("today")
        NSWorkspace.shared.open(url)
    }

    @objc
    private func openSystemSettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else {
            return
        }
        NSWorkspace.shared.open(url)
    }

    @objc
    private func toggleTracking() {
        store.trackingEnabled.toggle()
        rebuildMenu()
    }

    @objc
    private func quitHelper() {
        NSApplication.shared.terminate(nil)
    }

    private var shouldShowSetupAction: Bool {
        store.backendConfiguration == nil || !store.helperLastError.isEmpty
    }

    private var menuBarActionTitle: String {
        if store.backendConfiguration == nil {
            return "Connect Vero"
        }
        if !store.helperLastError.isEmpty {
            return "Repair Menu Bar Companion"
        }
        return "Open Vero"
    }
}
