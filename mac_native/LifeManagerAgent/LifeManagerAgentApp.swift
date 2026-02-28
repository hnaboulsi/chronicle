import AppKit
import SwiftUI

@main
struct LifeManagerAgentApp: App {
    @NSApplicationDelegateAdaptor(AgentAppDelegate.self) private var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

@MainActor
final class AgentAppDelegate: NSObject, NSApplicationDelegate {
    private let runtime = AgentRuntime()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.prohibited)
        runtime.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        runtime.stop()
    }
}
