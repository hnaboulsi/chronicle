import SwiftUI

struct TrackingView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            Section("Connection") {
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
            }

            Section {
                Toggle("Tracking Enabled", isOn: $model.settings.tracking_enabled)
                Stepper(value: $model.settings.polling_interval_seconds, in: 60 ... 3600, step: 60) {
                    HStack {
                        Text("Activity Check Interval")
                        Spacer()
                        Text("\(model.settings.polling_interval_seconds)s")
                            .foregroundStyle(.secondary)
                    }
                }
                Stepper(value: $model.settings.classification_interval_seconds, in: 300 ... 3600, step: 60) {
                    HStack {
                        Text("Classification Interval")
                        Spacer()
                        Text("\(model.settings.classification_interval_seconds)s")
                            .foregroundStyle(.secondary)
                    }
                }
            } header: {
                Text("Tracking")
            } footer: {
                Text("How frequently the app checks your active window and sends telemetry.")
            }

            Section {
                Picker("AI Provider", selection: $model.settings.ai_provider) {
                    Text("Auto").tag("auto")
                    Text("Gemini").tag("gemini")
                    Text("OpenAI").tag("openai")
                }
                Picker("Mode", selection: $model.settings.llm_mode) {
                    Text("Ultra Save").tag("ultra_save")
                    Text("Balanced").tag("balanced")
                    Text("Quality").tag("quality")
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
                Text("AI & Intelligence")
            } footer: {
                Text("Controls how often AI analyzes your activity and how verbose notifications are.")
            }

            Section {
                HStack {
                    Text("Status")
                    Spacer()
                    StatusBadge(
                        label: model.helperDesiredState.capitalized,
                        color: model.helperDesiredState == "enabled" ? .green : .orange
                    )
                }
                if !model.helperLastError.isEmpty {
                    HStack {
                        Text("Last Error")
                            .foregroundStyle(.red)
                        Spacer()
                        Text(model.helperLastError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            } header: {
                Text("Background Agent")
            } footer: {
                Text("The background agent runs silently and sends heartbeats every 60 seconds.")
            }
        }
        .formStyle(.grouped)
        .navigationTitle(isDirty ? "Tracking *" : "Tracking")
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
}
