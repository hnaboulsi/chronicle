import SwiftUI

struct CalendarView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        LabeledContent("Recommended") {
                            Text("Use an iCloud-backed \"Life Manager\" calendar")
                                .foregroundStyle(.secondary)
                        }
                        LabeledContent("Detected") {
                            Text("\(CalendarSyncEngine.shared.preferredCalendarName()) via \(CalendarSyncEngine.shared.targetDescription())")
                        }
                        LabeledContent("Permission") {
                            Text(model.permissionSnapshot.calendar.capitalized)
                                .foregroundStyle(model.permissionSnapshot.calendar == "granted" ? .green : .orange)
                        }
                        LabeledContent("Setup Hint") {
                            Text(CalendarSyncEngine.shared.setupRecommendation())
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                } label: {
                    Label("Calendar Setup", systemImage: "calendar.badge.checkmark")
                        .font(.headline)
                }

                GroupBox {
                    if model.calendarJobs.isEmpty {
                        Text("No pending calendar jobs.")
                            .foregroundStyle(.secondary)
                    } else {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(model.calendarJobs, id: \.self) { job in
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(job.title)
                                            .font(.body.weight(.medium))
                                        Text("\(job.kind) \u{2022} attempts: \(job.attempts)")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        if !job.last_error.isEmpty {
                                            Text(job.last_error)
                                                .font(.caption)
                                                .foregroundStyle(.red)
                                        }
                                    }
                                    Spacer()
                                    Text(job.status.capitalized)
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(job.status == "done" ? .green : (job.status == "failed" ? .red : .orange))
                                }
                                .padding(.vertical, 4)
                                if job != model.calendarJobs.last {
                                    Divider()
                                }
                            }
                        }
                    }
                } label: {
                    Label("Pending Jobs", systemImage: "tray.full")
                        .font(.headline)
                }
            }
            .padding(24)
        }
    }
}
