import SwiftUI

struct iPhoneSetupView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) var openURL

    var body: some View {
        Form {
            // Zone Automations
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "mappin.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.indigo)
                        Text("Step 1 — Set Up Zone Automations")
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
                            Text("• Arrive — Triggers when you enter the zone")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("• Leave — Triggers when you exit the zone")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        DisclosureGroup("ARRIVE Automation (8 Steps)") {
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

                        DisclosureGroup("LEAVE Automation (7 Steps)") {
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
                                Text("Before the 'Get Contents of URL' step, you can set a Focus mode:")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                ForEach(model.zones, id: \.slug) { zone in
                                    Text("• \(zone.name): Set Focus → (choose your mode)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                if model.zones.isEmpty {
                                    Text("(Add zones to see examples)")
                                        .font(.caption)
                                        .foregroundStyle(.tertiary)
                                        .italic()
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
                            let leaveURL = backendURL.absoluteString + "/api/ios-zone-event?zone_slug=\(zone.slug)&transition=exit"

                            VStack(alignment: .leading, spacing: Spacing.sm) {
                                Text(zone.name)
                                    .font(.subheadline.weight(.semibold))

                                HStack(spacing: Spacing.xs) {
                                    Image(systemName: "mappin.circle.fill")
                                        .foregroundStyle(.green)
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
                                    CopyButton(text: enterURL)
                                }

                                HStack(spacing: Spacing.xs) {
                                    Image(systemName: "door.right.hand.open")
                                        .foregroundStyle(.red)
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
                                    CopyButton(text: leaveURL)
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

            // Charging Automations
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "bolt.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.orange)
                        Text("Step 2 — Charging Automations")
                            .font(.subheadline.weight(.semibold))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Create automations to track when your iPhone is charging.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                DisclosureGroup("Setup Instructions (4 Steps)") {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        ForEach([
                            "1. Open Shortcuts app → Automation tab → + New Automation",
                            "2. Choose Charger → Is Connected (for charging on)",
                            "3. Add action: Get Contents of URL → paste the CHARGING ON URL (see below)",
                            "4. Repeat for Is Disconnected using the CHARGING OFF URL"
                        ], id: \.self) { step in
                            Text(step)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.top, Spacing.xs)
                }

                if let backendURL = model.store.backendURL {
                    let chargeOnURL = backendURL.absoluteString + "/api/ios-event?kind=charge_on"
                    let chargeOffURL = backendURL.absoluteString + "/api/ios-event?kind=charge_off"

                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("Charging On URL:")
                            .font(.caption.weight(.semibold))
                        HStack(spacing: Spacing.xs) {
                            Text(chargeOnURL)
                                .font(.system(.caption2, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .foregroundStyle(.blue)
                            CopyButton(text: chargeOnURL)
                        }

                        Text("Charging Off URL:")
                            .font(.caption.weight(.semibold))
                            .padding(.top, Spacing.sm)
                        HStack(spacing: Spacing.xs) {
                            Text(chargeOffURL)
                                .font(.system(.caption2, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .foregroundStyle(.blue)
                            CopyButton(text: chargeOffURL)
                        }
                    }
                }
            }

            // Walking Automation
            Section {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "figure.walk.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.green)
                        Text("Step 3 — Walking Automation")
                            .font(.subheadline.weight(.semibold))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Text("Create an automation to track when you're walking (Apple Watch).")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                DisclosureGroup("Setup Instructions (4 Steps)") {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        ForEach([
                            "1. Open Shortcuts app → Automation tab → + New Automation",
                            "2. Choose Apple Watch Workout → Walking → Starts",
                            "3. Add action: Get Contents of URL → paste the WALKING URL (see below)",
                            "4. Turn off Ask Before Running"
                        ], id: \.self) { step in
                            Text(step)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.top, Spacing.xs)
                }

                if let backendURL = model.store.backendURL {
                    let walkingURL = backendURL.absoluteString + "/api/ios-event?kind=walking"

                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("Walking URL:")
                            .font(.caption.weight(.semibold))
                        HStack(spacing: Spacing.xs) {
                            Text(walkingURL)
                                .font(.system(.caption2, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .foregroundStyle(.blue)
                            CopyButton(text: walkingURL)
                        }
                    }
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
