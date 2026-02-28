import SwiftUI

struct iPhoneSetupView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) var openURL

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                // Shortcuts Download
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionHeaderLabel("Step 1 — Download Shortcuts", icon: "arrow.down.circle.fill", color: .indigo)

                    Text("Download these shortcuts to your Mac, then AirDrop them to your iPhone.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    VStack(spacing: Spacing.md) {
                        if let backendURL = model.store.backendURL {
                            ForEach([("walking", "Walking"), ("charge_on", "Charging On"), ("charge_off", "Charging Off")], id: \.0) { kind, label in
                                Button(action: {
                                    let downloadURL = backendURL.appendingPathComponent("setup/shortcut/download")
                                        .appending(queryItems: [.init(name: "kind", value: kind)])
                                    openURL(downloadURL)
                                }) {
                                    HStack {
                                        Image(systemName: "arrow.down")
                                        Text(label)
                                        Spacer()
                                    }
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.bordered)
                            }
                        } else {
                            Text("Backend not configured")
                                .foregroundStyle(.red)
                        }
                    }

                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("⚠️ Signing Required (Railway)")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.orange)
                        Text("If using Railway, shortcuts must be signed. Run this in Terminal after downloading:")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if let backendURL = model.store.backendURL {
                            let command = """
                            for kind in walking charge_on charge_off; do
                              curl -s "\(backendURL.absoluteString)/setup/shortcut/download?kind=$kind" -o "Vero-$kind.shortcut" && \\
                              shortcuts sign -m anyone -i "Vero-$kind.shortcut" -o "Vero-$kind.shortcut"
                            done
                            """

                            HStack {
                                VStack(alignment: .leading) {
                                    Text(command)
                                        .font(.system(.caption, design: .monospaced))
                                        .lineLimit(nil)
                                        .foregroundStyle(.primary)
                                }
                                Spacer()
                                Button(action: {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(command, forType: .string)
                                }) {
                                    Image(systemName: "doc.on.doc")
                                }
                                .buttonStyle(.plain)
                            }
                            .padding(Spacing.md)
                            .background(.gray.opacity(0.1))
                            .cornerRadius(8)
                        }
                    }
                }

                Divider()

                // Zone Automations
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionHeaderLabel("Step 2 — Set Up Zone Automations", icon: "mappin.circle.fill", color: .indigo)

                    Text("Create iOS Shortcut automations for your zones. Use the URLs below in the Shortcuts app.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    if model.zones.isEmpty {
                        HStack {
                            Image(systemName: "exclamationmark.circle")
                                .foregroundStyle(.orange)
                            Text("No zones configured. Set up zones in the Zones tab first.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        VStack(spacing: Spacing.md) {
                            ForEach(model.zones, id: \.slug) { zone in
                                if let backendURL = model.store.backendURL {
                                    let enterURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=enter"
                                    let leaveURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=leave"

                                    VStack(alignment: .leading, spacing: Spacing.sm) {
                                        Text(zone.name)
                                            .font(.subheadline.weight(.semibold))

                                        VStack(alignment: .leading, spacing: Spacing.xs) {
                                            Text("Arrive:")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                            HStack {
                                                Text(enterURL)
                                                    .font(.system(.caption, design: .monospaced))
                                                    .lineLimit(1)
                                                    .truncationMode(.middle)
                                                    .foregroundStyle(.blue)
                                                Button(action: {
                                                    NSPasteboard.general.clearContents()
                                                    NSPasteboard.general.setString(enterURL, forType: .string)
                                                }) {
                                                    Image(systemName: "doc.on.doc")
                                                        .font(.caption)
                                                }
                                                .buttonStyle(.plain)
                                            }
                                        }

                                        VStack(alignment: .leading, spacing: Spacing.xs) {
                                            Text("Leave:")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                            HStack {
                                                Text(leaveURL)
                                                    .font(.system(.caption, design: .monospaced))
                                                    .lineLimit(1)
                                                    .truncationMode(.middle)
                                                    .foregroundStyle(.blue)
                                                Button(action: {
                                                    NSPasteboard.general.clearContents()
                                                    NSPasteboard.general.setString(leaveURL, forType: .string)
                                                }) {
                                                    Image(systemName: "doc.on.doc")
                                                        .font(.caption)
                                                }
                                                .buttonStyle(.plain)
                                            }
                                        }
                                    }
                                    .padding(Spacing.md)
                                    .background(.gray.opacity(0.05))
                                    .cornerRadius(8)
                                }
                            }
                        }
                    }
                }

                Divider()

                // Full Setup Guide
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionHeaderLabel("Step 3 — More Information", icon: "book.circle.fill", color: .indigo)

                    if let backendURL = model.store.backendURL {
                        Button(action: {
                            let setupURL = backendURL.appendingPathComponent("setup/ios")
                            openURL(setupURL)
                        }) {
                            HStack {
                                Image(systemName: "globe")
                                Text("Open Full Setup Guide")
                                Spacer()
                                Image(systemName: "arrow.up.right")
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
            .padding(Spacing.xl)
        }
        .navigationTitle("iPhone Setup")
    }
}

#Preview {
    iPhoneSetupView()
        .environmentObject(NativeAppModel())
}
