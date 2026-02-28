import Foundation

enum BackendError: Error {
    case invalidResponse
}

final class BackendClient {
    static let shared = BackendClient()

    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    private let store = AppGroupStore.shared

    private init() {
        self.session = URLSession(configuration: .default)
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    private func request(path: String, method: String = "GET", jsonBody: [String: Any]? = nil) throws -> URLRequest {
        let url = store.backendURL.appendingPathComponent(path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 10
        if !store.authValue.isEmpty {
            let token = Data(store.authValue.utf8).base64EncodedString()
            request.setValue("Basic \(token)", forHTTPHeaderField: "Authorization")
        }
        if let jsonBody {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: jsonBody, options: [])
        }
        return request
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func perform(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200 ..< 300).contains(http.statusCode) else {
            throw BackendError.invalidResponse
        }
        return data
    }

    func fetchState() async throws -> DashboardState {
        let data = try await perform(try request(path: "api/state"))
        return try decode(DashboardState.self, from: data)
    }

    func fetchSettings() async throws -> BackendSettings {
        let data = try await perform(try request(path: "api/settings"))
        return try decode(BackendSettings.self, from: data)
    }

    func saveSettings(_ settings: BackendSettings) async throws {
        let body: [String: Any] = [
            "polling_interval_seconds": settings.polling_interval_seconds,
            "tracking_enabled": settings.tracking_enabled,
            "backend_mode": settings.backend_mode,
            "ai_provider": settings.ai_provider,
            "llm_mode": settings.llm_mode,
            "hourly_summaries_enabled": settings.hourly_summaries_enabled,
            "classification_interval_seconds": settings.classification_interval_seconds,
            "llm_daily_cap": settings.llm_daily_cap,
            "user_timezone": settings.user_timezone,
        ]
        _ = try await perform(try request(path: "api/settings", method: "POST", jsonBody: body))
    }

    func fetchZones() async throws -> [ZoneRecord] {
        let data = try await perform(try request(path: "api/zones"))
        return try decode(ZoneListResponse.self, from: data).zones
    }

    func save(zone: ZoneRecord) async throws {
        let body: [String: Any] = [
            "slug": zone.slug,
            "name": zone.name,
            "radius_meters": zone.radius_meters,
            "enabled": zone.enabled,
            "zone_type": zone.zone_type,
            "focus_mode": zone.focus_mode,
            "sort_order": zone.sort_order,
        ]
        let path = zone.id == nil ? "api/zones" : "api/zones/\(zone.id!)"
        let method = zone.id == nil ? "POST" : "PATCH"
        _ = try await perform(try request(path: path, method: method, jsonBody: body))
    }

    func delete(zone: ZoneRecord) async throws {
        guard let id = zone.id else { return }
        _ = try await perform(try request(path: "api/zones/\(id)", method: "DELETE"))
    }

    func fetchCalendarJobs() async throws -> [CalendarJob] {
        let data = try await perform(try request(path: "api/calendar/jobs"))
        return try decode(CalendarJobsResponse.self, from: data).jobs
    }

    func ackCalendarJob(id: Int) async throws {
        _ = try await perform(try request(path: "api/calendar/jobs/\(id)/ack", method: "POST", jsonBody: [:]))
    }

    func failCalendarJob(id: Int, error: String) async throws {
        _ = try await perform(try request(path: "api/calendar/jobs/\(id)/fail", method: "POST", jsonBody: ["error": error]))
    }

    func fetchHealth() async throws -> HealthResponse {
        let data = try await perform(try request(path: "api/healthz"))
        return try decode(HealthResponse.self, from: data)
    }

    func fetchChatHistory() async throws -> [ChatTurn] {
        let data = try await perform(try request(path: "api/chat/history"))
        return try decode(ChatHistoryResponse.self, from: data).messages
    }

    func fetchCallout() async throws -> CalloutResponse {
        let data = try await perform(try request(path: "api/callout"))
        return try decode(CalloutResponse.self, from: data)
    }

    func fetchCheckin() async throws -> CheckinResponse {
        let data = try await perform(try request(path: "api/checkin"))
        return try decode(CheckinResponse.self, from: data)
    }

    func sendHeartbeat(clientID: String, appVersion: String, agentState: String, trackingEnabled: Bool, permissionsState: String, lastError: String) async throws {
        let body: [String: Any] = [
            "client_id": clientID,
            "app_version": appVersion,
            "agent_state": agentState,
            "tracking_enabled": trackingEnabled,
            "permissions_state": permissionsState,
            "last_error": lastError,
        ]
        _ = try await perform(try request(path: "api/mac-heartbeat", method: "POST", jsonBody: body))
    }

    func sendTelemetry(appName: String, windowTitle: String, idleTimeSeconds: Int) async throws {
        let body: [String: Any] = [
            "app_name": appName,
            "window_title": windowTitle,
            "idle_time_seconds": idleTimeSeconds,
        ]
        _ = try await perform(try request(path: "api/mac-telemetry", method: "POST", jsonBody: body))
    }
}
