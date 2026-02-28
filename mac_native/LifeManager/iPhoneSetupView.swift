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

                    Text("Create location-based automations in the iOS Shortcuts app to track when you enter and leave your zones.")
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
                        VStack(alignment: .leading, spacing: Spacing.lg) {
                            // Quick Summary
                            VStack(alignment: .leading, spacing: Spacing.sm) {
                                Text("For each zone, you'll create two automations:")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                VStack(alignment: .leading, spacing: Spacing.xs) {
                                    Text("• 📍 Arrive — Triggers when you enter the zone")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                    Text("• 🚪 Leave — Triggers when you exit the zone")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(Spacing.md)
                            .background(.orange.opacity(0.08))
                            .cornerRadius(8)

                            // Detailed Instructions
                            VStack(alignment: .leading, spacing: Spacing.md) {
                                Text("Step-by-Step Instructions:")
                                    .font(.caption.weight(.semibold))

                                VStack(alignment: .leading, spacing: Spacing.sm) {
                                    Text("For the ARRIVE automation:")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.primary)

                                    VStack(alignment: .leading, spacing: Spacing.xs) {
                                        ForEach([
                                            "1. Open Shortcuts app → go to Automation tab",
                                            "2. Tap + (New Automation) → Location",
                                            "3. Select your zone (search by name)",
                                            "4. Choose Arrival time (optional radius: 50-100m)",
                                            "5. Tap Next → disable 'Ask Before Running'",
                                            "6. Add action: Get Contents of URL",
                                            "7. Paste the ARRIVE URL (see below) into URL field",
                                            "8. Tap Next → Done"
                                        ], id: \.self) { step in
                                            Text(step)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(nil)
                                        }
                                    }
                                }

                                VStack(alignment: .leading, spacing: Spacing.sm) {
                                    Text("For the LEAVE automation:")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.primary)

                                    VStack(alignment: .leading, spacing: Spacing.xs) {
                                        ForEach([
                                            "1. Tap + (New Automation) → Location",
                                            "2. Select your zone again",
                                            "3. Choose Leaving time (same radius)",
                                            "4. Tap Next → disable 'Ask Before Running'",
                                            "5. Add action: Get Contents of URL",
                                            "6. Paste the LEAVE URL (see below)",
                                            "7. Tap Next → Done"
                                        ], id: \.self) { step in
                                            Text(step)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(nil)
                                        }
                                    }
                                }

                                VStack(alignment: .leading, spacing: Spacing.sm) {
                                    Text("Optional: Add Focus Mode actions")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.primary)

                                    VStack(alignment: .leading, spacing: Spacing.xs) {
                                        Text("Before the 'Get Contents of URL' step, you can add:")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        ForEach([
                                            "• Dwinelle Hall: Set Focus → Class",
                                            "• Wheeler Hall: Set Focus → Class",
                                            "• VLSB: Set Focus → Deep Work",
                                            "• Doe/Moffitt: Set Focus → Deep Work",
                                            "• Anchor House: Set Focus → Off (on arrival only)"
                                        ], id: \.self) { step in
                                            Text(step)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                }
                            }
                            .padding(Spacing.md)
                            .background(.blue.opacity(0.05))
                            .cornerRadius(8)

                            // Zone URLs
                            Text("Zone Automation URLs (tap to copy):")
                                .font(.caption.weight(.semibold))

                            VStack(spacing: Spacing.md) {
                                ForEach(model.zones, id: \.slug) { zone in
                                    if let backendURL = model.store.backendURL {
                                        let enterURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=enter"
                                        let leaveURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=leave"

                                        VStack(alignment: .leading, spacing: Spacing.sm) {
                                            Text(zone.name)
                                                .font(.subheadline.weight(.semibold))

                                            VStack(alignment: .leading, spacing: Spacing.xs) {
                                                Text("📍 Arrive URL:")
                                                    .font(.caption)
                                                    .foregroundStyle(.secondary)
                                                HStack {
                                                    Text(enterURL)
                                                        .font(.system(.caption2, design: .monospaced))
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
                                                Text("🚪 Leave URL:")
                                                    .font(.caption)
                                                    .foregroundStyle(.secondary)
                                                HStack {
                                                    Text(leaveURL)
                                                        .font(.system(.caption2, design: .monospaced))
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
                }

                Divider()

                // Step Counting
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionHeaderLabel("Step 3 — Step Counting (Optional)", icon: "figure.walk.circle.fill", color: .green)

                    Text("Send daily step count to Vero automatically every hour using an iOS Shortcut automation.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    if let backendURL = model.store.backendURL {
                        let telemetryURL = backendURL.absoluteString + "/api/ios-telemetry"

                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("How to set up:")
                                .font(.caption.weight(.semibold))

                            VStack(alignment: .leading, spacing: Spacing.xs) {
                                ForEach([
                                    "1. Open the Shortcuts app → tap + to create a new shortcut",
                                    "2. Add \"Get My Health Samples\" → Category: Activity, Type: Steps, Period: Today",
                                    "3. Add \"Calculate Statistics\" → Sum",
                                    "4. Add \"Get Contents of URL\":",
                                    "   • URL: (see below)",
                                    "   • Method: POST",
                                    "   • Body: JSON → add key \"steps_today\" = Statistics Result",
                                    "5. Save as \"Vero Steps\"",
                                    "6. Go to Automation → New → Time of Day → Every Hour",
                                    "7. Action: Run Shortcut → Vero Steps → turn off Ask Before Running",
                                ], id: \.self) { step in
                                    Text(step)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }

                            VStack(alignment: .leading, spacing: Spacing.xs) {
                                Text("POST URL (tap to copy):")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                HStack {
                                    Text(telemetryURL)
                                        .font(.system(.caption, design: .monospaced))
                                        .lineLimit(1)
                                        .truncationMode(.middle)
                                        .foregroundStyle(.blue)
                                    Button(action: {
                                        NSPasteboard.general.clearContents()
                                        NSPasteboard.general.setString(telemetryURL, forType: .string)
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

                Divider()

                // Full Setup Guide
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionHeaderLabel("Step 4 — More Information", icon: "book.circle.fill", color: .indigo)

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
