import Foundation

final class AppGroupStore {
    static let shared = AppGroupStore()

    private let defaults = UserDefaults(suiteName: AppConstants.appGroupIdentifier)

    private init() {}

    var backendURL: URL {
        get {
            if let string = defaults?.string(forKey: "backend_url"),
               let url = URL(string: string) {
                return url
            }
            return AppConstants.defaultBackendURL
        }
        set {
            defaults?.set(newValue.absoluteString, forKey: "backend_url")
        }
    }

    var authValue: String {
        get { defaults?.string(forKey: "auth_value") ?? "" }
        set { defaults?.set(newValue, forKey: "auth_value") }
    }

    var trackingEnabled: Bool {
        get {
            if defaults?.object(forKey: "tracking_enabled") == nil {
                return true
            }
            return defaults?.bool(forKey: "tracking_enabled") ?? true
        }
        set {
            defaults?.set(newValue, forKey: "tracking_enabled")
        }
    }

    var aiProvider: String {
        get { defaults?.string(forKey: "ai_provider") ?? "auto" }
        set { defaults?.set(newValue, forKey: "ai_provider") }
    }

    var notificationLevel: NotificationLevel {
        get {
            let raw = defaults?.string(forKey: "notification_level") ?? NotificationLevel.normal.rawValue
            return NotificationLevel(rawValue: raw) ?? .normal
        }
        set {
            defaults?.set(newValue.rawValue, forKey: "notification_level")
        }
    }

    var pollingInterval: Int {
        get {
            let value = defaults?.integer(forKey: "polling_interval_seconds") ?? 60
            return value == 0 ? 60 : value
        }
        set {
            defaults?.set(newValue, forKey: "polling_interval_seconds")
        }
    }

    var classificationInterval: Int {
        get {
            let value = defaults?.integer(forKey: "classification_interval_seconds") ?? 300
            return value == 0 ? 300 : value
        }
        set {
            defaults?.set(newValue, forKey: "classification_interval_seconds")
        }
    }

    var migrationComplete: Bool {
        get { defaults?.bool(forKey: "migration_complete") ?? false }
        set { defaults?.set(newValue, forKey: "migration_complete") }
    }

    var helperDesiredState: String {
        get { defaults?.string(forKey: "helper_desired_state") ?? "enabled" }
        set { defaults?.set(newValue, forKey: "helper_desired_state") }
    }

    var helperLastError: String {
        get { defaults?.string(forKey: "helper_last_error") ?? "" }
        set { defaults?.set(newValue, forKey: "helper_last_error") }
    }

    var helperLastSeenAt: Date? {
        get { defaults?.object(forKey: "helper_last_seen_at") as? Date }
        set { defaults?.set(newValue, forKey: "helper_last_seen_at") }
    }

    var clientID: String {
        if let value = defaults?.string(forKey: "client_id"), !value.isEmpty {
            return value
        }
        let value = UUID().uuidString
        defaults?.set(value, forKey: "client_id")
        return value
    }
}
