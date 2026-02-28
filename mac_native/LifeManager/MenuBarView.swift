import SwiftUI

struct MenuBarView: View {
    @EnvironmentObject private var model: NativeAppModel
    @EnvironmentObject private var menuBar: MenuBarManager
    @Environment(\.openURL) var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Status
            HStack(spacing: 8) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Status")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(model.state.mac_status?.replacingOccurrences(of: "_", with: " ").capitalized ?? "Unknown")
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
                Spacer()
            }
            .padding(.vertical, 8)
            .padding(.horizontal, 10)

            Divider()

            // Current Activity
            HStack(spacing: 8) {
                Image(systemName: "figure.walk")
                    .foregroundStyle(.blue)

                VStack(alignment: .leading, spacing: 2) {
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
            .padding(.vertical, 8)
            .padding(.horizontal, 10)

            Divider()

            // Current App
            HStack(spacing: 8) {
                Image(systemName: "app.dashed")
                    .foregroundStyle(.orange)

                VStack(alignment: .leading, spacing: 2) {
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
            .padding(.vertical, 8)
            .padding(.horizontal, 10)

            Divider()

            // Actions
            VStack(spacing: 0) {
                Button(action: {
                    if let url = NSApplication.shared.windows.first?.windowScene?.windows.first?.windowLevel {
                        NSApplication.shared.windows.first?.makeKeyAndOrderFront(nil)
                    } else {
                        openURL(URL(string: "lifemanager://open")!)
                    }
                }) {
                    HStack {
                        Image(systemName: "rectangle.portrait")
                        Text("Open Dashboard")
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
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
                        Text("Quit Life Manager")
                        Spacer()
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
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
        .padding(.vertical, 8)
    }

    private var statusColor: Color {
        switch model.state.mac_status {
        case "online", "online_idle": return .green
        case "paused": return .orange
        case "offline": return .red
        default: return .gray
        }
    }
}

#Preview {
    MenuBarView()
        .environmentObject(NativeAppModel())
        .environmentObject(MenuBarManager.shared)
}
