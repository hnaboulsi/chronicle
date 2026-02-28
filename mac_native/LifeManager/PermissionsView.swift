import SwiftUI

struct PermissionsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                GroupBox {
                    VStack(alignment: .leading, spacing: 12) {
                        permissionRow(name: "Accessibility", status: model.permissionSnapshot.accessibility, description: "Required for reading window titles.")
                        Divider()
                        permissionRow(name: "Notifications", status: model.permissionSnapshot.notifications, description: "Enables check-in prompts and focus nudges.")
                        Divider()
                        permissionRow(name: "Calendar", status: model.permissionSnapshot.calendar, description: "Allows syncing productive sessions to Apple Calendar.")
                    }
                } label: {
                    Label("Permission Status", systemImage: "lock.shield")
                        .font(.headline)
                }

                GroupBox {
                    VStack(spacing: 10) {
                        Button(action: { model.openSystemSettings() }) {
                            Label("Open Accessibility Settings", systemImage: "hand.raised")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)

                        Button(action: { requestCalendarAccess() }) {
                            Label("Request Calendar Access", systemImage: "calendar.badge.plus")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)

                        Button(action: {
                            Task { model.permissionSnapshot = await PermissionSnapshot.capture() }
                        }) {
                            Label("Refresh Permissions", systemImage: "arrow.clockwise")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }
                } label: {
                    Label("Actions", systemImage: "gearshape")
                        .font(.headline)
                }
            }
            .padding(24)
        }
    }

    private func permissionRow(name: String, status: String, description: String) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.body.weight(.medium))
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(status.capitalized)
                .font(.callout.weight(.semibold))
                .foregroundStyle(permissionColor(status))
        }
    }

    private func permissionColor(_ status: String) -> Color {
        switch status.lowercased() {
        case "granted": return .green
        case "denied", "restricted": return .red
        case "pending", "not determined": return .orange
        default: return .secondary
        }
    }

    private func requestCalendarAccess() {
        Task {
            await CalendarSyncEngine.shared.requestAccessIfNeeded()
            model.permissionSnapshot = await PermissionSnapshot.capture()
        }
    }
}
