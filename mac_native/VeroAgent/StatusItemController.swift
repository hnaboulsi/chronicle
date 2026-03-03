import AppKit
import SwiftUI

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let store = AppGroupStore.shared
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private lazy var popover: NSPopover = {
        let p = NSPopover()
        p.contentSize = NSSize(width: 320, height: 350)
        p.behavior = .transient
        p.contentViewController = NSHostingController(rootView: AgentPopoverView())
        return p
    }()

    func start() {
        if let button = statusItem.button {
            let config = NSImage.SymbolConfiguration(pointSize: 15, weight: .semibold)
            let image = NSImage(systemSymbolName: "waveform.path.ecg", accessibilityDescription: "Vero")
            image?.isTemplate = true
            button.image = image?.withSymbolConfiguration(config)
            button.toolTip = "Vero"
            button.action = #selector(togglePopover(_:))
            button.target = self
        }
    }

    @objc private func togglePopover(_ sender: AnyObject?) {
        if let button = statusItem.button {
            if popover.isShown {
                popover.performClose(sender)
            } else {
                popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            }
        }
    }

    func stop() {
        if popover.isShown {
            popover.performClose(nil)
        }
        NSStatusBar.system.removeStatusItem(statusItem)
    }
}
