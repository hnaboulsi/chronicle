import SwiftUI

struct TrackingView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Backend")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(model.store.backendURL?.absoluteString ?? "Not configured")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Text("Authentication")
                    Spacer()
                    StatusBadge(
                        label: model.store.authValue.isEmpty ? "Not Set" : "Configured",
                        color: model.store.authValue.isEmpty ? .orange : .green
                    )
                }
            } header: {
                Text("Connection")
            }

            Section {
                Toggle("Tracking Enabled", isOn: $model.settings.tracking_enabled)

                Picker("Capture Interval", selection: captureIntervalBinding) {
                    Text("1 minute").tag(60)
                    Text("5 minutes").tag(300)
                    Text("15 minutes").tag(900)
                }

                Picker("Privacy Mode", selection: $model.settings.privacy_mode) {
                    Text("Private by Default").tag("private")
                    Text("Detailed Capture").tag("detailed")
                }

                Toggle("Calendar Sync", isOn: $model.settings.calendar_sync_enabled)
            } header: {
                Text("Tracking")
            } footer: {
                Text("Capture interval controls how often Vero records activity. Heartbeats still run every 60 seconds in the background for health checks only.")
            }

            Section {
                Picker("AI Provider", selection: $model.settings.ai_provider) {
                    Text("Auto").tag("auto")
                    Text("Gemini").tag("gemini")
                    Text("OpenAI").tag("openai")
                }

                Stepper(value: $model.settings.llm_daily_cap, in: 1 ... 500, step: 1) {
                    HStack {
                        Text("Daily AI Calls")
                        Spacer()
                        Text("\(model.settings.llm_daily_cap)")
                            .foregroundStyle(.secondary)
                    }
                }

                Picker("Notifications", selection: $model.notificationLevel) {
                    ForEach(NotificationLevel.allCases) { level in
                        Text(level.rawValue.capitalized).tag(level)
                    }
                }
            } header: {
                Text("Intelligence")
            } footer: {
                Text("AI summaries are optional. Reliability and activity capture continue even when the daily AI cap is exhausted.")
            }

            Section {
                HStack {
                    Text("Helper")
                    Spacer()
                    StatusBadge(
                        label: model.helperDesiredState.capitalized,
                        color: model.helperDesiredState == "enabled" ? .green : .orange
                    )
                }
                InfoRow(label: "Presence", value: presenceLabel(model.state.presence_state))
                InfoRow(label: "Last Heartbeat", value: ageString(model.state.last_mac_heartbeat_age_seconds))
                InfoRow(label: "Last Capture", value: ageString(model.state.last_mac_capture_age_seconds))
                InfoRow(label: "Mac Status", value: model.state.mac_status_reason ?? "Waiting for agent")
                if !model.helperLastError.isEmpty {
                    InfoRow(label: "Last Error", value: model.helperLastError, color: .red)
                }
            } header: {
                Text("Agent Health")
            }
        }
        .formStyle(.grouped)
        .navigationTitle(isDirty ? "Tracking & Privacy *" : "Tracking & Privacy")
        .animation(.easeInOut(duration: 0.2), value: model.settings)
        .animation(.easeInOut(duration: 0.2), value: model.notificationLevel)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Menu {
                    Button("Enable", action: { model.enableHelper() })
                    Button("Disable", action: { model.disableHelper() })
                    Button("Repair", action: { model.repairHelper() })
                } label: {
                    Label("Agent", systemImage: "gearshape.2")
                }

                Button(action: { Task { await model.saveSettings() } }) {
                    Label("Save", systemImage: "checkmark")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!isDirty)
            }
        }
    }

    private var isDirty: Bool {
        model.settings != model.lastSavedSettings || model.notificationLevel != model.lastSavedNotificationLevel
    }

    private var captureIntervalBinding: Binding<Int> {
        Binding(
            get: { model.settings.capture_interval_seconds },
            set: { newValue in
                model.settings.capture_interval_seconds = newValue
                model.settings.polling_interval_seconds = newValue
                model.settings.classification_interval_seconds = max(300, newValue)
            }
        )
    }

    private func ageString(_ value: Int?) -> String {
        guard let value else { return "Unknown" }
        if value < 60 { return "\(value)s ago" }
        if value < 3600 { return "\(value / 60)m ago" }
        if value < 86_400 { return "\(value / 3600)h ago" }
        return "\(value / 86_400)d ago"
    }

    private func presenceLabel(_ value: String?) -> String {
        switch (value ?? "").lowercased() {
        case "active":
            return "Active"
        case "idle":
            return "Idle"
        case "away":
            return "Away"
        case "locked":
            return "Locked"
        case "sleeping":
            return "Sleeping"
        default:
            return "Unknown"
        }
    }
}
