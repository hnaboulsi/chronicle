import Foundation
import UserNotifications

final class AgentNotificationManager {
    static let shared = AgentNotificationManager()

    private var recentlyDelivered: [String: Date] = [:]

    private init() {}

    func requestAuthorizationIfNeeded() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            guard settings.authorizationStatus == .notDetermined else { return }
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { _, _ in }
        }
    }

    func deliver(kind: AgentNotificationKind, title: String, body: String, ttl: TimeInterval = 900) {
        guard shouldDeliver(kind: kind, title: title, body: body, ttl: ttl) else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: kind.rawValue + ":" + String(body.prefix(64)),
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    private func shouldDeliver(kind: AgentNotificationKind, title: String, body: String, ttl: TimeInterval) -> Bool {
        let level = AppGroupStore.shared.notificationLevel
        if level == .minimal && kind != .critical {
            return false
        }

        let key = kind.rawValue + "|" + title + "|" + body
        let now = Date()
        if let prior = recentlyDelivered[key], now.timeIntervalSince(prior) < ttl {
            return false
        }
        recentlyDelivered[key] = now
        if recentlyDelivered.count > 32 {
            recentlyDelivered = recentlyDelivered.filter { now.timeIntervalSince($0.value) < ttl }
        }
        return true
    }
}

enum AgentNotificationKind: String {
    case critical
    case checkin
    case callout
}
