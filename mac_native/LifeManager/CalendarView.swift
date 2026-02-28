import SwiftUI

struct CalendarView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                LabeledContent("Calendar Target") {
                    Text(CalendarSyncEngine.shared.preferredCalendarName())
                }
                LabeledContent("Calendar Permission") {
                    Text(model.permissionSnapshot.calendar)
                }
                Text("Pending Jobs")
                    .font(.headline)
                if model.calendarJobs.isEmpty {
                    Text("No pending calendar jobs.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(model.calendarJobs, id: \.self) { job in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(job.title)
                            Text("\(job.kind) • attempts: \(job.attempts)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .padding(24)
        }
    }
}
