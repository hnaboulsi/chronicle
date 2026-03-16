import SwiftUI

struct PermissionsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            Section {
                PermissionRowItem(
                    icon: "hand.raised",
                    name: "Accessibility",
                    description: "Required to read window titles and detect your active application.",
                    status: model.permissionSnapshot.accessibility,
                    action: {
                        model.openSystemSettings()
                    }
                )

                PermissionRowItem(
                    icon: "bell.badge",
                    name: "Notifications",
                    description: "Enables check-in prompts, focus nudges, and activity alerts.",
                    status: model.permissionSnapshot.notifications,
                    action: nil
                )

                PermissionRowItem(
                    icon: "calendar.badge.plus",
                    name: "Calendar",
                    description: "Syncs your productive sessions to Apple Calendar.",
                    status: model.permissionSnapshot.calendar,
                    action: {
                        Task {
                            await CalendarSyncEngine.shared.requestAccessIfNeeded()
                            model.permissionSnapshot = await PermissionSnapshot.capture()
                        }
                    }
                )
            } header: {
                Text("System Permissions")
            } footer: {
                Text("All permissions can be managed in System Settings under Security & Privacy.")
            }

            Section {
                Button(action: { model.openSystemSettings() }) {
                    Label("Open System Settings", systemImage: "gear")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)

                Button(action: {
                    Task { model.permissionSnapshot = await PermissionSnapshot.capture() }
                }) {
                    Label("Refresh Status", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.bordered)
            } header: {
                Text("Actions")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Permissions")
        .animation(.spring(), value: model.permissionSnapshot)
    }
}

private struct PermissionRowItem: View {
    let icon: String
    let name: String
    let description: String
    let status: String
    let action: (() -> Void)?

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(permissionColor(status))
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.subheadline.weight(.semibold))
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 16)

            VStack(spacing: 6) {
                StatusBadge(label: status.capitalized, color: permissionColor(status))
                if let action = action {
                    if status != "granted" {
                        Button(action: action) {
                            Text("Request")
                                .font(.caption.weight(.semibold))
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }
}
