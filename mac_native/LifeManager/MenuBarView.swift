import SwiftUI

struct MenuBarView: View {
    @EnvironmentObject private var model: NativeAppModel
    @EnvironmentObject private var menuBar: MenuBarManager

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Agent Status with error dot
            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(model.helperLastError.isEmpty ? Color.green : Color.red)
                    .frame(width: 8, height: 8)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Agent")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(model.helperLastError.isEmpty ? "Running" : "Error")
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                }
                Spacer()
            }
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)

            Divider()

            // Current App
            if !menuBar.currentApp.isEmpty {
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
            }

            // Error Message if Present
            if !model.helperLastError.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Error")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.red)
                    Text(model.helperLastError)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }
                .padding(.vertical, Spacing.sm)
                .padding(.horizontal, Spacing.md)

                Divider()
            }

            // Actions
            VStack(spacing: 0) {
                Button(action: { model.openWebDashboard() }) {
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

                Button(role: .destructive, action: {
                    NSApplication.shared.terminate(nil)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { exit(0) }
                }) {
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
