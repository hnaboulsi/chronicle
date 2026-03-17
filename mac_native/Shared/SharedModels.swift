import Foundation

struct BackendConfiguration {
    let baseURL: URL
    let authValue: String
}

struct BackendSettings: Codable, Equatable {
    var capture_interval_seconds: Int
    var polling_interval_seconds: Int
    var tracking_enabled: Bool
    var backend_mode: String
    var ai_provider: String
    var llm_mode: String
    var hourly_summaries_enabled: Bool
    var classification_interval_seconds: Int
    var llm_daily_cap: Int
    var user_timezone: String
    var privacy_mode: String
    var calendar_sync_enabled: Bool

    init(
        capture_interval_seconds: Int,
        polling_interval_seconds: Int? = nil,
        tracking_enabled: Bool,
        backend_mode: String,
        ai_provider: String,
        llm_mode: String,
        hourly_summaries_enabled: Bool,
        classification_interval_seconds: Int,
        llm_daily_cap: Int,
        user_timezone: String,
        privacy_mode: String,
        calendar_sync_enabled: Bool
    ) {
        let capture = max(60, capture_interval_seconds)
        self.capture_interval_seconds = capture
        self.polling_interval_seconds = polling_interval_seconds ?? capture
        self.tracking_enabled = tracking_enabled
        self.backend_mode = backend_mode
        self.ai_provider = ai_provider
        self.llm_mode = llm_mode
        self.hourly_summaries_enabled = hourly_summaries_enabled
        self.classification_interval_seconds = max(300, classification_interval_seconds)
        self.llm_daily_cap = llm_daily_cap
        self.user_timezone = user_timezone
        self.privacy_mode = privacy_mode
        self.calendar_sync_enabled = calendar_sync_enabled
    }

    private enum CodingKeys: String, CodingKey {
        case capture_interval_seconds
        case polling_interval_seconds
        case tracking_enabled
        case backend_mode
        case ai_provider
        case llm_mode
        case hourly_summaries_enabled
        case classification_interval_seconds
        case llm_daily_cap
        case user_timezone
        case privacy_mode
        case calendar_sync_enabled
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let capture = try container.decodeIfPresent(Int.self, forKey: .capture_interval_seconds)
            ?? container.decodeIfPresent(Int.self, forKey: .polling_interval_seconds)
            ?? 300
        self.init(
            capture_interval_seconds: capture,
            polling_interval_seconds: try container.decodeIfPresent(Int.self, forKey: .polling_interval_seconds) ?? capture,
            tracking_enabled: try container.decode(Bool.self, forKey: .tracking_enabled),
            backend_mode: try container.decode(String.self, forKey: .backend_mode),
            ai_provider: try container.decode(String.self, forKey: .ai_provider),
            llm_mode: try container.decode(String.self, forKey: .llm_mode),
            hourly_summaries_enabled: try container.decode(Bool.self, forKey: .hourly_summaries_enabled),
            classification_interval_seconds: try container.decodeIfPresent(Int.self, forKey: .classification_interval_seconds) ?? max(300, capture),
            llm_daily_cap: try container.decode(Int.self, forKey: .llm_daily_cap),
            user_timezone: try container.decode(String.self, forKey: .user_timezone),
            privacy_mode: try container.decodeIfPresent(String.self, forKey: .privacy_mode) ?? "private",
            calendar_sync_enabled: try container.decodeIfPresent(Bool.self, forKey: .calendar_sync_enabled) ?? true
        )
    }
}

struct DashboardState: Codable {
    var backend_target_url: String?
    var mac_status: String?
    var mac_status_reason: String?
    var mac_idle: Bool?
    var last_mac_heartbeat_age_seconds: Int?
    var last_mac_capture_age_seconds: Int?
    var last_mac_snapshot_age_seconds: Int?
    var last_heartbeat_at: String?
    var last_capture_at: String?
    var presence_state: String?
    var last_presence_change_at: String?
    var screen_state: String?
    var current_activity_category: String?
    var current_activity_summary: String?
    var current_location: String?
    var ios_recent_event: Bool?
    var user_timezone: String?
    var sleep_status_note: String?
    var likely_asleep: String?
    var likely_asleep_reason: String?
    var likely_asleep_confidence: String?
    var service_health: String?
    var tracking_enabled: String?
    var capture_interval_seconds: Int?
    var privacy_mode: String?
    var calendar_sync_enabled: Bool?
}

struct ZoneRecord: Codable, Identifiable, Hashable {
    var id: Int?
    var slug: String
    var name: String
    var radius_meters: Int
    var enabled: Bool
    var zone_type: String
    var focus_mode: String
    var sort_order: Int
    var is_default: Bool?

    static let empty = ZoneRecord(
        id: nil,
        slug: "",
        name: "",
        radius_meters: 75,
        enabled: true,
        zone_type: "custom",
        focus_mode: "",
        sort_order: 0,
        is_default: false
    )
}

struct ZoneListResponse: Codable {
    let zones: [ZoneRecord]
}

struct CalendarJob: Codable, Identifiable, Hashable {
    let id: Int
    let kind: String
    let title: String
    let notes: String
    let start_at: String
    let end_at: String
    let status: String
    let attempts: Int
    let last_error: String
}

struct CalendarJobsResponse: Codable {
    let jobs: [CalendarJob]
}

struct TelemetryResponse: Codable {
    let status: String
    let prompt: String?
}

struct HeartbeatResponse: Codable {
    let status: String
    let mac_status: String?
    let mac_status_reason: String?
    let tracking_enabled: Bool?
    let capture_interval_seconds: Int?
}

struct HealthResponse: Codable {
    struct Build: Codable {
        let build_version: String?
        let deployment_channel: String?
        let git_sha: String?
    }

    struct DatabaseStatus: Codable {
        let ok: Bool?
        let error: String?
    }

    struct MacStatus: Codable {
        let status: String?
        let reason: String?
    }

    struct CalendarStatus: Codable {
        let pending_jobs: Int?
        let executor: String?
    }

    let status: String
    let build: Build?
    let database: DatabaseStatus?
    let startup_errors: [String]?
    let uptime_seconds: Int?
    let mac: MacStatus?
    let calendar: CalendarStatus?
}

struct ChatTurn: Codable, Hashable {
    let time: String
    let user: String
    let reply: String
}

struct ChatHistoryResponse: Codable {
    let messages: [ChatTurn]
}

struct CalloutResponse: Codable {
    let callout: String?
    let category: String?
}

struct CheckinResponse: Codable {
    let checkin: String?
    let guess: String?
    let created_at: String?
    let expires_at: String?
    let age_seconds: Int?
    let can_snooze: Bool?
    let can_dismiss: Bool?
}

struct ContextPreferences: Codable {
    let current_intent: String
    let sleep_start_hour: Int
    let sleep_end_hour: Int
    let special_mode: String
}

struct IOSSetupChecklistItem: Codable, Hashable {
    let id: String
    let label: String
    let configured: Bool?
}

struct IOSSetupZone: Codable, Hashable {
    let id: Int?
    let slug: String
    let name: String
    let arrive_url: String?
    let leave_url: String?
    let arrive_shortcut_url: String?
    let leave_shortcut_url: String?
}

struct IOSSetupEvents: Codable, Hashable {
    let walking_url: String
    let charge_on_url: String
    let charge_off_url: String
}

struct IOSSetupPackResponse: Codable {
    let backend_url: String
    let zones: [IOSSetupZone]
    let required: [IOSSetupChecklistItem]
    let optional: [IOSSetupChecklistItem]
    let events: IOSSetupEvents
    let shortcuts: [String: String]?
}

struct IOSSetupStatusResponse: Codable {
    let ios_recent_ping: Bool?
    let last_ios_ping_age_seconds: Int?
    let sleep_source: String?
    let sleep_status_note: String?
    let required: [IOSSetupChecklistItem]?
    let optional: [IOSSetupChecklistItem]?
}

enum NotificationLevel: String, CaseIterable, Identifiable {
    case minimal
    case normal
    case verbose

    var id: String { rawValue }
}
