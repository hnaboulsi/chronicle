import Foundation

final class AppGroupStore {
    static let shared = AppGroupStore()

    private let defaults = UserDefaults(suiteName: AppConstants.appGroupIdentifier)

    private init() {}

    var backendURL: URL? {
        get {
            if let string = defaults?.string(forKey: "backend_url"),
               let url = URL(string: string) {
                return url
            }
            return nil
        }
        set {
            defaults?.set(newValue?.absoluteString, forKey: "backend_url")
        }
    }

    var validatedBackendURL: URL? {
        guard let rawValue = defaults?.string(forKey: "backend_url") else {
            return nil
        }
        return Self.validatedCloudBackendURL(from: rawValue)
    }

    var backendConfiguration: BackendConfiguration? {
        guard let baseURL = validatedBackendURL else {
            return nil
        }

        let trimmedAuth = authValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAuth.isEmpty else {
            return nil
        }

        return BackendConfiguration(baseURL: baseURL, authValue: trimmedAuth)
    }

    var isConfigured: Bool {
        backendConfiguration != nil
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

    var captureInterval: Int {
        get {
            let captureValue = defaults?.integer(forKey: "capture_interval_seconds") ?? 0
            if captureValue > 0 {
                return captureValue
            }
            let legacyValue = defaults?.integer(forKey: "polling_interval_seconds") ?? 300
            return legacyValue == 0 ? 300 : legacyValue
        }
        set {
            defaults?.set(newValue, forKey: "capture_interval_seconds")
            defaults?.set(newValue, forKey: "polling_interval_seconds")
        }
    }

    var pollingInterval: Int {
        get { captureInterval }
        set { captureInterval = newValue }
    }

    var privacyMode: String {
        get {
            let raw = defaults?.string(forKey: "privacy_mode") ?? "private"
            return raw.isEmpty ? "private" : raw
        }
        set {
            defaults?.set(newValue, forKey: "privacy_mode")
        }
    }

    var calendarSyncEnabled: Bool {
        get {
            if defaults?.object(forKey: "calendar_sync_enabled") == nil {
                return true
            }
            return defaults?.bool(forKey: "calendar_sync_enabled") ?? true
        }
        set {
            defaults?.set(newValue, forKey: "calendar_sync_enabled")
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

    var legacyPythonWarningShown: Bool {
        get { defaults?.bool(forKey: "legacy_python_warning_shown") ?? false }
        set { defaults?.set(newValue, forKey: "legacy_python_warning_shown") }
    }

    var clientID: String {
        if let value = defaults?.string(forKey: "client_id"), !value.isEmpty {
            return value
        }
        let value = UUID().uuidString
        defaults?.set(value, forKey: "client_id")
        return value
    }

    func clearInvalidConfiguration() {
        guard let rawValue = defaults?.string(forKey: "backend_url"), !rawValue.isEmpty else {
            return
        }

        if Self.validatedCloudBackendURL(from: rawValue) == nil {
            backendURL = nil
        }
    }

    static func validatedCloudBackendURL(from value: String) -> URL? {
        let trimmedValue = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedValue.isEmpty, let url = URL(string: trimmedValue) else {
            return nil
        }
        return isAllowedCloudBackendURL(url) ? url : nil
    }

    static func isAllowedCloudBackendURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "https" else {
            return false
        }

        guard let host = url.host?.lowercased(), !host.isEmpty else {
            return false
        }

        if ["localhost", "127.0.0.1", "0.0.0.0", "::1"].contains(host) {
            return false
        }

        if host.hasSuffix(".local") {
            return false
        }

        return true
    }
}
