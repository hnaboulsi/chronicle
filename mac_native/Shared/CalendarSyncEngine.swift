import EventKit
import Foundation

final class CalendarSyncEngine {
    static let shared = CalendarSyncEngine()

    private let store = EKEventStore()

    private init() {}

    private enum SyncError: LocalizedError {
        case calendarUnavailable
        case invalidDate(String)

        var errorDescription: String? {
            switch self {
            case .calendarUnavailable:
                return "Vero could not access or create the target calendar."
            case let .invalidDate(value):
                return "Invalid calendar timestamp: \(value)"
            }
        }
    }

    func authorizationStatus() -> EKAuthorizationStatus {
        EKEventStore.authorizationStatus(for: .event)
    }

    func requestAccessIfNeeded() async {
        guard authorizationStatus() == .notDetermined else { return }
        if #available(macOS 14.0, *) {
            _ = try? await store.requestFullAccessToEvents()
        } else {
            await withCheckedContinuation { continuation in
                store.requestAccess(to: .event) { _, _ in
                    continuation.resume()
                }
            }
        }
    }

    func preferredCalendarName() -> String {
        calendar()?.title ?? AppConstants.calendarName
    }

    func hasICloudSource() -> Bool {
        preferredSource()?.sourceType == .calDAV && (preferredSource()?.title.localizedCaseInsensitiveContains("icloud") ?? false)
    }

    func targetDescription() -> String {
        hasICloudSource() ? "iCloud Calendar" : "On My Mac fallback"
    }

    func setupRecommendation() -> String {
        if hasICloudSource() {
            return "Keep iCloud Calendar enabled and make sure the Vero calendar stays under the iCloud section in Calendar.app."
        }
        return "Turn on System Settings > Apple Account > iCloud > Calendar, then create or move the Vero calendar under the iCloud section in Calendar.app."
    }

    func readTodayEvents() -> [[String: Any]] {
        let status = authorizationStatus()
        if #available(macOS 14.0, *) {
            guard status == .fullAccess || status == .writeOnly else { return [] }
        } else {
            guard status == .authorized else { return [] }
        }
        let now = Date()
        let cal = Foundation.Calendar.current
        let dayStart = cal.startOfDay(for: now)
        guard let dayEnd = cal.date(byAdding: .day, value: 2, to: dayStart) else { return [] }
        let predicate = store.predicateForEvents(withStart: dayStart, end: dayEnd, calendars: nil)
        let events = store.events(matching: predicate)
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return events.compactMap { event -> [String: Any]? in
            guard let start = event.startDate, let end = event.endDate, let title = event.title else { return nil }
            guard event.calendar?.title != AppConstants.calendarName else { return nil }
            var dict: [String: Any] = [
                "event_uid": event.eventIdentifier ?? "",
                "title": title,
                "start_at": formatter.string(from: start),
                "end_at": formatter.string(from: end),
            ]
            if let calName = event.calendar?.title { dict["calendar_name"] = calName }
            if let notes = event.notes, !notes.isEmpty { dict["notes"] = String(notes.prefix(500)) }
            if let location = event.location, !location.isEmpty { dict["location"] = location }
            return dict
        }
    }

    func syncPendingJobs(client: BackendClient = .shared) async {
        await requestAccessIfNeeded()
        let status = authorizationStatus()
        if #available(macOS 14.0, *) {
            guard status == .fullAccess || status == .writeOnly else { return }
        } else {
            guard status == .authorized else { return }
        }
        do {
            let jobs = try await client.fetchCalendarJobs()
            for job in jobs where job.status == "pending" {
                do {
                    try write(job: job)
                    try await client.ackCalendarJob(id: job.id)
                } catch {
                    try? await client.failCalendarJob(id: job.id, error: error.localizedDescription)
                }
            }
        } catch {
            AppGroupStore.shared.helperLastError = error.localizedDescription
        }
    }

    private func calendar() -> EKCalendar? {
        if let existing = store.calendars(for: .event).first(where: { $0.title == AppConstants.calendarName }) {
            return existing
        }

        guard let source = preferredSource() else { return nil }
        let calendar = EKCalendar(for: .event, eventStore: store)
        calendar.title = AppConstants.calendarName
        calendar.source = source
        do {
            try store.saveCalendar(calendar, commit: true)
            return calendar
        } catch {
            AppGroupStore.shared.helperLastError = error.localizedDescription
            return nil
        }
    }

    private func preferredSource() -> EKSource? {
        let sources = store.sources
        if let icloud = sources.first(where: { $0.title.localizedCaseInsensitiveContains("icloud") }) {
            return icloud
        }
        return sources.first
    }

    private func write(job: CalendarJob) throws {
        guard let calendar = calendar() else {
            throw SyncError.calendarUnavailable
        }
        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = job.title
        event.notes = job.notes
        event.startDate = try parseDate(job.start_at)
        event.endDate = try parseDate(job.end_at)
        if event.endDate <= event.startDate {
            event.endDate = event.startDate.addingTimeInterval(600)
        }
        try store.save(event, span: .thisEvent, commit: true)
    }

    private func parseDate(_ value: String) throws -> Date {
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = isoFormatter.date(from: value) {
            return date
        }

        let fallbackISO = ISO8601DateFormatter()
        if let date = fallbackISO.date(from: value) {
            return date
        }

        let plainFormatter = DateFormatter()
        plainFormatter.locale = Locale(identifier: "en_US_POSIX")
        plainFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        plainFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        if let date = plainFormatter.date(from: value) {
            return date
        }

        let fractionalFormatter = DateFormatter()
        fractionalFormatter.locale = Locale(identifier: "en_US_POSIX")
        fractionalFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        fractionalFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        if let date = fractionalFormatter.date(from: value) {
            return date
        }

        throw SyncError.invalidDate(value)
    }
}
