import SwiftUI

struct iPhoneSetupView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) private var openURL

    var body: some View {
        Form {
            Section("Setup Status") {
                if let status = model.iosSetupStatus {
                    checklistRow(title: "Required", items: status.required ?? [])
                    checklistRow(title: "Optional", items: status.optional ?? [])
                    if let note = status.sleep_status_note, !note.isEmpty {
                        Text(note)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    ProgressView("Loading setup status…")
                }
            }

            Section {
                Text("Fastest path: in Shortcuts, create Location personal automations for each zone with Arrive + Leave triggers, and use 'Get Contents of URL' with the generated links below.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if (model.iosSetupPack?.zones ?? []).isEmpty {
                    Label("No zones configured yet. Add zones in the Zones tab first.", systemImage: "exclamationmark.circle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            } footer: {
                Text("Apple does not provide an API to auto-create Personal Automations, so Arrive/Leave triggers still need to be created once per zone.")
                    .font(.caption)
            }

            Section("Zone URLs (Required)") {
                ForEach(model.iosSetupPack?.zones ?? [], id: \.slug) { zone in
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(zone.name)
                            .font(.subheadline.weight(.semibold))
                        if let arrive = zone.arrive_url {
                            HStack {
                                Text(arrive)
                                    .font(.system(.caption2, design: .monospaced))
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                CopyButton(text: arrive)
                            }
                        }
                        if let leave = zone.leave_url {
                            HStack {
                                Text(leave)
                                    .font(.system(.caption2, design: .monospaced))
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                CopyButton(text: leave)
                            }
                        }
                        if let arriveShortcut = zone.arrive_shortcut_url, let url = URL(string: arriveShortcut) {
                            HStack {
                                Text("Arrive shortcut")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Button("Download") { openURL(url) }
                                    .buttonStyle(.bordered)
                            }
                        }
                        if let leaveShortcut = zone.leave_shortcut_url, let url = URL(string: leaveShortcut) {
                            HStack {
                                Text("Leave shortcut")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Button("Download") { openURL(url) }
                                    .buttonStyle(.bordered)
                            }
                        }
                    }
                }
            }

            Section("Optional URLs") {
                if let events = model.iosSetupPack?.events {
                    helperURLRow(title: "Walking", url: events.walking_url)
                    helperURLRow(title: "Charge On", url: events.charge_on_url)
                    helperURLRow(title: "Charge Off", url: events.charge_off_url)
                } else {
                    Text("Loading optional event URLs…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                if let links = model.iosSetupPack?.shortcuts {
                    shortcutDownloadRow(title: "Walking Shortcut", url: links["walking"])
                    shortcutDownloadRow(title: "Charge On Shortcut", url: links["charge_on"])
                    shortcutDownloadRow(title: "Charge Off Shortcut", url: links["charge_off"])
                } else {
                    Text("Loading shortcut links…")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Helper Shortcut Downloads")
            } footer: {
                Text("You can attach these to Personal Automations using 'Run Shortcut' to reduce setup friction.")
                    .font(.caption)
            }

            Section("Open Full Guide") {
                if let setupBase = model.iosSetupPack?.backend_url, let url = URL(string: setupBase + "/setup/ios") {
                    Button("Open Web iPhone Setup") { openURL(url) }
                        .buttonStyle(.borderedProminent)
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("iPhone Setup")
    }

    @ViewBuilder
    private func checklistRow(title: String, items: [IOSSetupChecklistItem]) -> some View {
        let configured = items.filter { $0.configured == true }.count
        HStack {
            Text(title)
            Spacer()
            Text("\(configured)/\(items.count)")
                .foregroundStyle(configured == items.count && !items.isEmpty ? .green : .secondary)
        }
    }

    @ViewBuilder
    private func helperURLRow(title: String, url: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            HStack {
                Text(url)
                    .font(.system(.caption2, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)
                CopyButton(text: url)
            }
        }
    }

    @ViewBuilder
    private func shortcutDownloadRow(title: String, url: String?) -> some View {
        if let raw = url, let parsed = URL(string: raw) {
            HStack {
                Text(title)
                Spacer()
                Button("Download") { openURL(parsed) }
                    .buttonStyle(.bordered)
            }
        }
    }
}

#Preview {
    iPhoneSetupView()
        .environmentObject(NativeAppModel())
}
