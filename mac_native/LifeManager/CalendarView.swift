import SwiftUI

struct CalendarView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            // Setup Section
            Form {
                Section("Setup Status") {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        HStack {
                            Text("Recommended")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text("iCloud-backed Vero calendar")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Text("Detected")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text("\(CalendarSyncEngine.shared.preferredCalendarName()) (\(CalendarSyncEngine.shared.targetDescription()))")
                                .font(.caption)
                        }
                        HStack {
                            Text("Permission")
                            Spacer()
                            StatusBadge(
                                label: model.permissionSnapshot.calendar.capitalized,
                                color: permissionColor(model.permissionSnapshot.calendar)
                            )
                        }
                    }
                    .padding(.vertical, Spacing.xs)

                    if model.permissionSnapshot.calendar != "granted" {
                        Button(action: {
                            Task {
                                await CalendarSyncEngine.shared.requestAccessIfNeeded()
                                model.permissionSnapshot = await PermissionSnapshot.capture()
                            }
                        }) {
                            Label("Request Calendar Access", systemImage: "calendar.badge.plus")
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.bordered)
                    }

                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("Setup Recommendation")
                            .font(.caption.weight(.semibold))
                        Text(CalendarSyncEngine.shared.setupRecommendation())
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, Spacing.xs)
                }
            }
            .formStyle(.grouped)

            // Jobs Section
            List {
                if model.calendarJobs.isEmpty {
                    Section {
                        HStack {
                            Spacer()
                            VStack(spacing: 8) {
                                Image(systemName: "calendar.badge.checkmark")
                                    .font(.system(size: 28))
                                    .foregroundStyle(.green)
                                Text("No Pending Jobs")
                                    .foregroundStyle(.secondary)
                                    .font(.subheadline)
                            }
                            Spacer()
                        }
                        .padding(.vertical, 32)
                    }
                } else {
                    Section("Pending Jobs") {
                        ForEach(model.calendarJobs, id: \.self) { job in
                            HStack(spacing: Spacing.md) {
                                VStack(alignment: .leading, spacing: Spacing.xs) {
                                    Text(job.title)
                                        .font(.subheadline.weight(.semibold))
                                    HStack(spacing: Spacing.xs) {
                                        Text(job.kind)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Text("•")
                                            .foregroundStyle(.secondary)
                                        Text("\(job.attempts) attempt\(job.attempts == 1 ? "" : "s")")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    if !job.last_error.isEmpty {
                                        Text(job.last_error)
                                            .font(.caption)
                                            .foregroundStyle(.red)
                                            .lineLimit(2)
                                    }
                                }
                                Spacer(minLength: Spacing.lg)
                                StatusBadge(
                                    label: job.status.capitalized,
                                    color: jobStatusColor(job.status)
                                )
                            }
                            .padding(.vertical, Spacing.xs)
                        }
                    }
                }
            }
            .listStyle(.inset)
        }
        .navigationTitle("Calendar")
    }
}
