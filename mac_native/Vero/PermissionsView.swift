import SwiftUI

struct PermissionsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        VStack(spacing: 0) {
            // ── Section header ──────────────────────────────────────────────
            HStack {
                Text("SYSTEM PERMISSIONS")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color.textMuted)
                    .tracking(0.6)
                Spacer()
                Button(action: {
                    Task { model.permissionSnapshot = await PermissionSnapshot.capture() }
                }) {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 11, weight: .regular))
                        .foregroundStyle(Color.textMuted)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 8)

            // ── Accessibility ───────────────────────────────────────────────
            PermissionRow(
                icon: "hand.raised",
                iconColor: .statusAmber,
                name: "Accessibility",
                description: "Required to read window and tab titles for activity tracking.",
                status: model.permissionSnapshot.accessibility,
                action: { model.requestAccessibilityPermission() }
            )

            Color.borderSubtle.frame(height: 1).padding(.leading, 60)

            // ── Notifications ───────────────────────────────────────────────
            PermissionRow(
                icon: "bell.badge",
                iconColor: .statusGreen,
                name: "Notifications",
                description: "Enables check-in prompts, focus nudges, and activity alerts.",
                status: model.permissionSnapshot.notifications,
                action: {
                    Task {
                        AgentNotificationManager.shared.requestAuthorizationIfNeeded()
                        model.permissionSnapshot = await PermissionSnapshot.capture()
                    }
                }
            )

            Color.borderSubtle.frame(height: 1).padding(.leading, 60)

            // ── Calendar ────────────────────────────────────────────────────
            PermissionRow(
                icon: "calendar.badge.plus",
                iconColor: model.permissionSnapshot.calendar == "granted" ? .statusGreen : .statusAmber,
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

            Color.borderSubtle.frame(height: 1).padding(.leading, 60)

            // ── Chrome Tab Titles ───────────────────────────────────────────
            PermissionRow(
                icon: "globe",
                iconColor: .statusGreen,
                name: "Chrome Tab Titles",
                description: "Allows Vero to read your browser tab titles to track what you're working on.",
                status: model.permissionSnapshot.appleEvents,
                action: { model.requestAppleEventsPermission() }
            )

            // ── Footer ──────────────────────────────────────────────────────
            VStack(alignment: .leading, spacing: 0) {
                Color.borderSubtle.frame(height: 1)
                Text("All permissions can be managed in System Settings under Security & Privacy. If Accessibility shows as Missing after an app update, toggle it OFF and ON again to re-grant.")
                    .font(.system(size: 11, weight: .regular))
                    .foregroundStyle(Color.textMuted)
                    .lineSpacing(3)
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 16)
            }
        }
        .background(Color.appBg)
        .animation(.easeInOut(duration: 0.15), value: model.permissionSnapshot)
    }
}

// MARK: - Permission Row

private struct PermissionRow: View {
    let icon: String
    let iconColor: Color
    let name: String
    let description: String
    let status: String
    let action: () -> Void

    @State private var isHovering = false
    @State private var requestHovering = false

    private var badgeLabel: String {
        switch status.lowercased() {
        case "granted":              return "Granted"
        case "denied", "restricted": return "Denied"
        case "pending":              return "Pending"
        default:                     return status.capitalized
        }
    }

    private var badgeColor: Color {
        switch status.lowercased() {
        case "granted":              return .statusGreen
        case "denied", "restricted": return .statusRed
        case "missing":              return .statusRed
        default:                     return .statusAmber
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            // Icon container
            ZStack {
                RoundedRectangle(cornerRadius: 7)
                    .fill(Color.surface)
                    .overlay(
                        RoundedRectangle(cornerRadius: 7)
                            .strokeBorder(Color.borderSubtle, lineWidth: 1)
                    )
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(iconColor)
            }
            .frame(width: 30, height: 30)

            // Name + description
            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.textPrimary)
                Text(description)
                    .font(.system(size: 12, weight: .regular))
                    .foregroundStyle(Color.textSecondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            // Badge + Request button
            VStack(alignment: .trailing, spacing: 6) {
                Text(badgeLabel)
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.2)
                    .foregroundStyle(badgeColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(badgeColor.opacity(0.10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 5)
                            .strokeBorder(badgeColor.opacity(0.20), lineWidth: 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 5))

                if status.lowercased() != "granted" {
                    Button(action: action) {
                        Text("Request")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(requestHovering ? Color.textPrimary : Color.textSecondary)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(requestHovering ? Color.surfaceHover : Color.surface)
                            .overlay(
                                RoundedRectangle(cornerRadius: 5)
                                    .strokeBorder(requestHovering ? Color.white.opacity(0.18) : Color.borderMedium, lineWidth: 1)
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 5))
                    }
                    .buttonStyle(.plain)
                    .onHover { h in withAnimation(.easeInOut(duration: 0.1)) { requestHovering = h } }
                }
            }
            .frame(minWidth: 70, alignment: .trailing)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(isHovering ? Color.surface.opacity(0.5) : Color.clear)
        .contentShape(Rectangle())
        .onHover { h in withAnimation(.easeInOut(duration: 0.1)) { isHovering = h } }
    }
}
