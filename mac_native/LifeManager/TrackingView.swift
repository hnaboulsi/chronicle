import SwiftUI

struct TrackingView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Connection
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        LabeledContent("Backend URL") {
                            Text(model.store.backendURL.absoluteString)
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        LabeledContent("Auth") {
                            Text(model.store.authValue.isEmpty ? "Not configured" : "Configured")
                                .foregroundStyle(model.store.authValue.isEmpty ? .orange : .green)
                        }
                    }
                } label: {
                    Label("Connection", systemImage: "network")
                        .font(.headline)
                }

                // Tracking Settings
                GroupBox {
                    Form {
                        Toggle("Tracking Enabled", isOn: $model.settings.tracking_enabled)
                        Stepper(value: $model.settings.polling_interval_seconds, in: 60 ... 3600, step: 60) {
                            Text("Telemetry Interval: \(model.settings.polling_interval_seconds)s")
                        }
                        Stepper(value: $model.settings.classification_interval_seconds, in: 300 ... 3600, step: 60) {
                            Text("Classification Interval: \(model.settings.classification_interval_seconds)s")
                        }
                    }
                    .formStyle(.columns)
                } label: {
                    Label("Tracking", systemImage: "dial.high")
                        .font(.headline)
                }

                // AI Settings
                GroupBox {
                    Form {
                        Picker("AI Provider", selection: $model.settings.ai_provider) {
                            Text("Auto").tag("auto")
                            Text("Gemini").tag("gemini")
                            Text("OpenAI").tag("openai")
                        }
                        Picker("LLM Mode", selection: $model.settings.llm_mode) {
                            Text("Ultra Save").tag("ultra_save")
                            Text("Balanced").tag("balanced")
                            Text("Quality").tag("quality")
                        }
                        Stepper(value: $model.settings.llm_daily_cap, in: 1 ... 500, step: 1) {
                            Text("Daily AI Cap: \(model.settings.llm_daily_cap)")
                        }
                        Picker("Notification Level", selection: $model.notificationLevel) {
                            ForEach(NotificationLevel.allCases) { level in
                                Text(level.rawValue.capitalized).tag(level)
                            }
                        }
                    }
                    .formStyle(.columns)
                } label: {
                    Label("AI & Notifications", systemImage: "brain")
                        .font(.headline)
                }

                // Actions
                GroupBox {
                    VStack(spacing: 10) {
                        Button(action: { Task { await model.saveSettings() } }) {
                            Text("Save Settings")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)

                        HStack(spacing: 10) {
                            Button("Enable Agent") { model.enableHelper() }
                                .buttonStyle(.bordered)
                            Button("Disable Agent") { model.disableHelper() }
                                .buttonStyle(.bordered)
                            Button("Repair Agent") { model.repairHelper() }
                                .buttonStyle(.bordered)
                        }
                    }
                } label: {
                    Label("Background Agent", systemImage: "gearshape.2")
                        .font(.headline)
                }
            }
            .padding(24)
        }
    }
}
