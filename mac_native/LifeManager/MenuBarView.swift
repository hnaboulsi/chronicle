import SwiftUI

struct MenuBarView: View {
    @EnvironmentObject private var model: NativeAppModel
    @EnvironmentObject private var menuBar: MenuBarManager
    @Environment(\.openURL) var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Status
            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(macStatusColor(model.state.mac_status))
                    .frame(width: 8, height: 8)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Status")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(model.state.mac_status?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown")
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
                Spacer()
            }
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)

            Divider()

            // Current Activity
            HStack(spacing: Spacing.sm) {
                Image(systemName: "figure.walk")
                    .foregroundStyle(.blue)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Activity")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(model.state.current_activity_category ?? "Unknown")
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                }
                Spacer()
            }
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)

            Divider()

            // Current App
            HStack(spacing: Spacing.sm) {
                Image(systemName: "app.dashed")
                    .foregroundStyle(.orange)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("App")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(menuBar.currentApp)
                        .font(.caption)
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                }
                Spacer()
            }
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)

            Divider()

            // Actions
            VStack(spacing: 0) {
                Button(action: {
                    openURL(URL(string: "\(AppConstants.urlScheme)://open")!)
                }) {
                    HStack {
                        Image(systemName: "rectangle.portrait")
                        Text("Open Dashboard")
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.vertical, Spacing.sm)
                .padding(.horizontal, Spacing.md)
                .onHover { isHovered in
                    if isHovered {
                        NSCursor.pointingHand.push()
                    } else {
                        NSCursor.pop()
                    }
                }

                Divider()

                Button(role: .destructive, action: { NSApplication.shared.terminate(nil) }) {
                    HStack {
                        Image(systemName: "xmark.circle")
                        Text("Quit Vero")
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.vertical, Spacing.sm)
                .padding(.horizontal, Spacing.md)
                .onHover { isHovered in
                    if isHovered {
                        NSCursor.pointingHand.push()
                    } else {
                        NSCursor.pop()
                    }
                }
            }
        }
        .frame(width: 280)
        .padding(.vertical, Spacing.sm)
}

#Preview {
    MenuBarView()
        .environmentObject(NativeAppModel())
        .environmentObject(MenuBarManager.shared)
}
