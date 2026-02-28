import AppKit

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let store = AppGroupStore.shared
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()

    private var summaryItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var lastSeenItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var openAppItem = NSMenuItem(title: "Open Life Manager", action: #selector(openApp), keyEquivalent: "")
    private var openDashboardItem = NSMenuItem(title: "Open Web Dashboard", action: #selector(openDashboard), keyEquivalent: "")
    private var toggleTrackingItem = NSMenuItem(title: "", action: #selector(toggleTracking), keyEquivalent: "")
    private var quitItem = NSMenuItem(title: "Quit Helper", action: #selector(quitHelper), keyEquivalent: "")

    func start() {
        if let button = statusItem.button {
            let config = NSImage.SymbolConfiguration(pointSize: 15, weight: .semibold)
            let image = NSImage(systemSymbolName: "waveform.path.ecg", accessibilityDescription: "Life Manager")
            image?.isTemplate = true
            button.image = image?.withSymbolConfiguration(config)
            button.toolTip = "Life Manager"
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

        openAppItem.target = self

        openDashboardItem.target = self
        openDashboardItem.isEnabled = store.backendConfiguration != nil

        toggleTrackingItem.title = store.trackingEnabled ? "Pause Tracking" : "Resume Tracking"
        toggleTrackingItem.target = self

        quitItem.target = self

        menu.removeAllItems()
        menu.addItem(summaryItem)
        menu.addItem(lastSeenItem)
        menu.addItem(.separator())
        menu.addItem(openAppItem)
        menu.addItem(openDashboardItem)
        menu.addItem(toggleTrackingItem)
        menu.addItem(.separator())
        menu.addItem(quitItem)
    }

    private var currentSummary: String {
        if let configuration = store.backendConfiguration {
            let host = configuration.baseURL.host ?? configuration.baseURL.absoluteString
            if !store.helperLastError.isEmpty {
                return "Issue: \(store.helperLastError)"
            }
            return store.trackingEnabled ? "Tracking enabled • \(host)" : "Tracking paused • \(host)"
        }
        return "Not connected to a cloud backend"
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
        let url = configuration.baseURL.appendingPathComponent("dashboard/index.html")
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
}
