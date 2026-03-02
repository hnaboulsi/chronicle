import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var currentIntent = ""
    @State private var sleepStartHour = 1
    @State private var sleepEndHour = 9
    @State private var specialMode = "normal"
    @State private var isSaving = false

    var body: some View {
        Form {
            Section("Current Intent") {
                TextField("What are you doing right now?", text: $currentIntent, axis: .vertical)
                    .lineLimit(3, reservesSpace: true)
                Text("This helps Vero interpret your activity and summaries.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Sleep Window") {
                Stepper(value: $sleepStartHour, in: 0 ... 23, step: 1) {
                    HStack {
                        Text("Sleep Start")
                        Spacer()
                        Text(hourLabel(sleepStartHour))
                            .foregroundStyle(.secondary)
                    }
                }
                Stepper(value: $sleepEndHour, in: 0 ... 23, step: 1) {
                    HStack {
                        Text("Sleep End")
                        Spacer()
                        Text(hourLabel(sleepEndHour))
                            .foregroundStyle(.secondary)
                    }
                }
                Text("Vero combines this schedule with charging and activity signals to estimate sleep.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Day Mode") {
                Picker("Special Mode", selection: $specialMode) {
                    Text("Normal").tag("normal")
                    Text("Travel").tag("travel")
                    Text("Exam").tag("exam")
                    Text("Rest").tag("rest")
                }
            }

            Section("Current Sleep Assessment") {
                Text(model.state.likely_asleep_reason ?? "No signal yet")
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                if let raw = model.state.likely_asleep_confidence, let confidence = Double(raw) {
                    ProgressView(value: confidence, total: 1.0) {
                        Text("Confidence")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section {
                Button(action: save) {
                    if isSaving {
                        ProgressView()
                    } else {
                        Text("Save Context")
                            .fontWeight(.semibold)
                    }
                }
                .disabled(isSaving)
            }

            if !model.chatTurns.isEmpty {
                Section("Recent Chat (for reference)") {
                    ForEach(Array(model.chatTurns.suffix(4).reversed().enumerated()), id: \.offset) { _, turn in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(formattedTime(turn.time))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text("You: \(turn.user)")
                                .font(.caption)
                            Text("Vero: \(turn.reply)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Context")
        .onAppear {
            syncFromModel()
        }
        .onChange(of: model.contextPreferences.current_intent) { _ in
            syncFromModel()
        }
    }

    private func syncFromModel() {
        currentIntent = model.contextPreferences.current_intent
        sleepStartHour = model.contextPreferences.sleep_start_hour
        sleepEndHour = model.contextPreferences.sleep_end_hour
        specialMode = model.contextPreferences.special_mode
    }

    private func hourLabel(_ hour: Int) -> String {
        let period = hour >= 12 ? "PM" : "AM"
        let normalized = hour % 12 == 0 ? 12 : hour % 12
        return "\(normalized):00 \(period)"
    }

    private func formattedTime(_ raw: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) {
            let display = DateFormatter()
            display.dateFormat = "h:mm a"
            display.timeZone = .current
            return display.string(from: date)
        }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) {
            let display = DateFormatter()
            display.dateFormat = "h:mm a"
            display.timeZone = .current
            return display.string(from: date)
        }
        return raw
    }

    private func save() {
        isSaving = true
        model.contextPreferences = ContextPreferences(
            current_intent: currentIntent,
            sleep_start_hour: sleepStartHour,
            sleep_end_hour: sleepEndHour,
            special_mode: specialMode
        )
        Task {
            await model.saveContextPreferences()
            isSaving = false
        }
    }
}

#Preview {
    ChatView()
        .environmentObject(NativeAppModel())
}
