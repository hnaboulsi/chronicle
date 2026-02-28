import EventKit
import Foundation

final class CalendarSyncEngine {
    static let shared = CalendarSyncEngine()

    private let store = EKEventStore()

    private init() {}

    func authorizationStatus() -> EKAuthorizationStatus {
        EKEventStore.authorizationStatus(for: .event)
    }

    func requestAccessIfNeeded() async {
        guard authorizationStatus() == .notDetermined else { return }
        _ = try? await store.requestFullAccessToEvents()
    }

    func preferredCalendarName() -> String {
        calendar()?.title ?? AppConstants.calendarName
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
        guard let calendar = calendar() else { return }
        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = job.title
        event.notes = job.notes
        let formatter = ISO8601DateFormatter()
        event.startDate = formatter.date(from: job.start_at) ?? Date()
        event.endDate = formatter.date(from: job.end_at) ?? Date().addingTimeInterval(600)
        try store.save(event, span: .thisEvent, commit: true)
    }
}
