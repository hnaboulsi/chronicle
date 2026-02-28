import Foundation

struct BackendSettings: Codable {
    var polling_interval_seconds: Int
    var tracking_enabled: Bool
    var backend_mode: String
    var ai_provider: String
    var llm_mode: String
    var hourly_summaries_enabled: Bool
    var classification_interval_seconds: Int
    var llm_daily_cap: Int
    var user_timezone: String
}

struct DashboardState: Codable {
    var backend_target_url: String?
    var mac_status: String?
    var mac_status_reason: String?
    var last_mac_heartbeat_age_seconds: Int?
    var last_mac_snapshot_age_seconds: Int?
    var current_activity_category: String?
    var current_activity_summary: String?
    var current_location: String?
    var ios_recent_event: Bool?
    var sleep_status_note: String?
    var service_health: String?
    var tracking_enabled: String?
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

struct HealthResponse: Codable {
    struct Build: Codable {
        let build_version: String
        let deployment_channel: String
        let git_sha: String
    }

    let status: String
    let build: Build?
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
}

enum NotificationLevel: String, CaseIterable, Identifiable {
    case minimal
    case normal
    case verbose

    var id: String { rawValue }
}
