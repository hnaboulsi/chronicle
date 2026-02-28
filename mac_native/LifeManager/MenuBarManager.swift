import AppKit
import Foundation

@MainActor
final class MenuBarManager: NSObject, ObservableObject {
    static let shared = MenuBarManager()

    @Published var isTracking = false
    @Published var currentApp = "System"
    @Published var lastUpdate = Date()

    private var trackingTimer: Timer?

    private override init() {
        super.init()
    }

    func startTracking() {
        guard trackingTimer == nil else { return }
        isTracking = true

        // Update every second
        trackingTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.updateCurrentApp()
            }
        }
    }

    func stopTracking() {
        trackingTimer?.invalidate()
        trackingTimer = nil
        isTracking = false
    }

    private func updateCurrentApp() {
        if let app = NSWorkspace.shared.frontmostApplication {
            currentApp = app.localizedName ?? "Unknown"
        }
        lastUpdate = Date()
    }

    deinit {
        stopTracking()
    }
}
