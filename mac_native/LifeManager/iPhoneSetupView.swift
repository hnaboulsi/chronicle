import SwiftUI

struct iPhoneSetupView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) var openURL
    @State private var copiedCommand = false

    var body: some View {
        Form {
            // Shortcuts Download
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "arrow.down.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.indigo)
                        Text("Step 1 — Download Shortcuts")
                            .font(.subheadline.weight(.semibold))

                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Download these shortcuts to your Mac, then AirDrop them to your iPhone.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

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
                        .font(.caption)
                }
            } footer: {
                if let backendURL = model.store.backendURL {
                    let command = """
                    for kind in walking charge_on charge_off; do
                      curl -s "\(backendURL.absoluteString)/setup/shortcut/download?kind=$kind" -o "Vero-$kind.shortcut" && \\
                      shortcuts sign -m anyone -i "Vero-$kind.shortcut" -o "Vero-$kind.shortcut"
                    done
                    """

                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        HStack(spacing: Spacing.xs) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(.orange)
                            Text("Signing Required (Railway)")
                                .font(.caption.weight(.semibold))
                        }
                        Text("If using Railway, shortcuts must be signed. Run this in Terminal after downloading:")
                            .font(.caption)

                        HStack(spacing: Spacing.sm) {
                            Text(command)
                                .font(.system(.caption2, design: .monospaced))
                                .lineLimit(nil)
                            Button(action: {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(command, forType: .string)
                                copiedCommand = true
                                DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                    copiedCommand = false
                                }
                            }) {
                                Image(systemName: copiedCommand ? "checkmark" : "doc.on.doc")
                            }
                            .buttonStyle(.plain)
                        }
                    }
                } else {
                    EmptyView()
                }
            }

            // Zone Automations
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "mappin.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.indigo)
                        Text("Step 2 — Set Up Zone Automations")
                            .font(.subheadline.weight(.semibold))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Create location-based automations in the iOS Shortcuts app to track when you enter and leave your zones.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if model.zones.isEmpty {
                    Label("No zones configured. Set up zones in the Zones tab first.", systemImage: "exclamationmark.circle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                } else {
                    VStack(alignment: .leading, spacing: Spacing.md) {
                        VStack(alignment: .leading, spacing: Spacing.xs) {
                            Text("For each zone, you'll create two automations:")
                                .font(.caption.weight(.semibold))
                            Text("• 📍 Arrive — Triggers when you enter the zone")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("• 🚪 Leave — Triggers when you exit the zone")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        DisclosureGroup("📍 ARRIVE Automation (8 Steps)") {
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
                                }
                            }
                            .padding(.top, Spacing.xs)
                        }

                        DisclosureGroup("🚪 LEAVE Automation (7 Steps)") {
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
                                }
                            }
                            .padding(.top, Spacing.xs)
                        }

                        DisclosureGroup("Optional: Focus Mode Integration") {
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
                            .padding(.top, Spacing.xs)
                        }
                    }
                }
            } footer: {
                if !model.zones.isEmpty {
                    Text("Copy each zone's URL and paste it into the 'Get Contents of URL' action in your automations.")
                        .font(.caption)
                } else {
                    EmptyView()
                }
            }

            // Zone URLs Section
            if !model.zones.isEmpty {
                Section {
                    ForEach(model.zones, id: \.slug) { zone in
                        if let backendURL = model.store.backendURL {
                            let enterURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=enter"
                            let leaveURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=leave"

                            VStack(alignment: .leading, spacing: Spacing.sm) {
                                Text(zone.name)
                                    .font(.subheadline.weight(.semibold))

                                HStack(spacing: Spacing.xs) {
                                    Text("📍")
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Arrive")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Text(enterURL)
                                            .font(.system(.caption2, design: .monospaced))
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                            .foregroundStyle(.blue)
                                    }
                                    Spacer()
                                    Button(action: {
                                        NSPasteboard.general.clearContents()
                                        NSPasteboard.general.setString(enterURL, forType: .string)
                                    }) {
                                        Image(systemName: "doc.on.doc")
                                    }
                                    .buttonStyle(.plain)
                                }

                                HStack(spacing: Spacing.xs) {
                                    Text("🚪")
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Leave")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Text(leaveURL)
                                            .font(.system(.caption2, design: .monospaced))
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                            .foregroundStyle(.blue)
                                    }
                                    Spacer()
                                    Button(action: {
                                        NSPasteboard.general.clearContents()
                                        NSPasteboard.general.setString(leaveURL, forType: .string)
                                    }) {
                                        Image(systemName: "doc.on.doc")
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                } header: {
                    Text("Zone Automation URLs")
                } footer: {
                    Text("Tap the copy button next to each URL to copy it to your clipboard.")
                }
            }

            // Step Counting
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "figure.walk.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.green)
                        Text("Step 3 — Step Counting (Optional)")
                            .font(.subheadline.weight(.semibold))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Send daily step count to Vero automatically every hour using an iOS Shortcut automation.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                DisclosureGroup("Setup Instructions (7 Steps)") {
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
                                .lineLimit(nil)
                        }
                    }
                    .padding(.top, Spacing.xs)
                }
            } footer: {
                if let backendURL = model.store.backendURL {
                    let telemetryURL = backendURL.absoluteString + "/api/ios-telemetry"
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text("POST URL:")
                            .font(.caption.weight(.semibold))
                        HStack(spacing: Spacing.xs) {
                            Text(telemetryURL)
                                .font(.system(.caption2, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Button(action: {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(telemetryURL, forType: .string)
                            }) {
                                Image(systemName: "doc.on.doc")
                            }
                            .buttonStyle(.plain)
                        }
                    }
                } else {
                    EmptyView()
                }
            }

            // More Information
            Section {
                if let backendURL = model.store.backendURL {
                    Button(action: {
                        let setupURL = backendURL.appendingPathComponent("setup/ios")
                        openURL(setupURL)
                    }) {
                        HStack {
                            Image(systemName: "book.circle.fill")
                                .foregroundStyle(.indigo)
                            Text("Open Full Setup Guide")
                            Spacer()
                            Image(systemName: "arrow.up.right")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.bordered)
                }
            } header: {
                Text("More Information")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("iPhone Setup")
    }
}

#Preview {
    iPhoneSetupView()
        .environmentObject(NativeAppModel())
}
