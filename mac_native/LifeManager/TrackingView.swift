import SwiftUI

struct TrackingView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            Toggle("Tracking Enabled", isOn: $model.settings.tracking_enabled)
            Stepper(value: $model.settings.polling_interval_seconds, in: 60 ... 3600, step: 60) {
                Text("Telemetry Interval: \(model.settings.polling_interval_seconds)s")
            }
            Stepper(value: $model.settings.classification_interval_seconds, in: 300 ... 3600, step: 60) {
                Text("Classification Interval: \(model.settings.classification_interval_seconds)s")
            }
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

            HStack {
                Button("Save Settings") {
                    Task { await model.saveSettings() }
                }
                Button("Enable Background Agent") {
                    model.enableHelper()
                }
                Button("Restart Background Agent") {
                    model.repairHelper()
                }
                Button("Disable Background Agent") {
                    model.disableHelper()
                }
                Button("Repair Registration") {
                    model.repairHelper()
                }
            }
        }
        .formStyle(.grouped)
        .padding(24)
    }
}
