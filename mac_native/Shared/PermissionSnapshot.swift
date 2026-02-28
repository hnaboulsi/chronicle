import ApplicationServices
import EventKit
import Foundation
import UserNotifications

struct PermissionSnapshot: Equatable {
    let accessibility: String
    let notifications: String
    let calendar: String
    let appleEvents: String

    static func capture() async -> PermissionSnapshot {
        let accessibility = AXIsProcessTrusted() ? "granted" : "missing"

        let calendarStatus = EKEventStore.authorizationStatus(for: .event)
        let calendar: String
        switch calendarStatus {
        case .authorized, .fullAccess, .writeOnly:
            calendar = "granted"
        case .denied:
            calendar = "denied"
        case .restricted:
            calendar = "restricted"
        case .notDetermined:
            calendar = "pending"
        @unknown default:
            calendar = "unknown"
        }

        let notificationSettings = await withCheckedContinuation { continuation in
            UNUserNotificationCenter.current().getNotificationSettings { settings in
                continuation.resume(returning: settings)
            }
        }
        let notifications: String
        switch notificationSettings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            notifications = "granted"
        case .denied:
            notifications = "denied"
        case .notDetermined:
            notifications = "pending"
        @unknown default:
            notifications = "unknown"
        }

        let appleEvents = AppGroupStore.shared.browserTabsGranted ? "granted" : "pending"

        return PermissionSnapshot(
            accessibility: accessibility,
            notifications: notifications,
            calendar: calendar,
            appleEvents: appleEvents
        )
    }
}
