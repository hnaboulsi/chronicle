import SwiftUI

struct ZonesView: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var draft = ZoneRecord.empty

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Zones drive the iPhone geofence model. Built-in zones can be edited but not deleted.")
                    .foregroundStyle(.secondary)

                VStack(alignment: .leading, spacing: 12) {
                    ForEach(model.zones, id: \.self) { zone in
                        ZoneEditorCard(zone: zone)
                            .environmentObject(model)
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 12) {
                    Text("Add Custom Zone").font(.headline)
                    TextField("Name", text: $draft.name)
                    TextField("Slug", text: $draft.slug)
                    Stepper(value: $draft.radius_meters, in: 25 ... 500, step: 5) {
                        Text("Radius: \(draft.radius_meters)m")
                    }
                    Picker("Type", selection: $draft.zone_type) {
                        Text("Custom").tag("custom")
                        Text("Home").tag("home")
                        Text("Lecture").tag("lecture")
                        Text("Study").tag("study")
                        Text("Gym").tag("gym")
                    }
                    TextField("Focus Hint", text: $draft.focus_mode)
                    Button("Create Zone") {
                        Task {
                            await model.save(zone: draft)
                            draft = .empty
                        }
                    }
                    .disabled(draft.name.isEmpty || draft.slug.isEmpty)
                }
            }
            .padding(24)
        }
    }
}

private struct ZoneEditorCard: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var editable: ZoneRecord

    init(zone: ZoneRecord) {
        _editable = State(initialValue: zone)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Name", text: $editable.name)
            TextField("Slug", text: $editable.slug)
                .disabled(editable.is_default ?? false)
            Stepper(value: $editable.radius_meters, in: 25 ... 500, step: 5) {
                Text("Radius: \(editable.radius_meters)m")
            }
            Picker("Type", selection: $editable.zone_type) {
                Text("Home").tag("home")
                Text("Lecture").tag("lecture")
                Text("Study").tag("study")
                Text("Gym").tag("gym")
                Text("Custom").tag("custom")
            }
            TextField("Focus Hint", text: $editable.focus_mode)
            Toggle("Enabled", isOn: $editable.enabled)

            Text("Enter payload: {\"zone_slug\":\"\(editable.slug)\",\"transition\":\"enter\"}")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("Exit payload: {\"zone_slug\":\"\(editable.slug)\",\"transition\":\"exit\"}")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                Button("Save") {
                    Task { await model.save(zone: editable) }
                }
                if !(editable.is_default ?? false) {
                    Button("Delete", role: .destructive) {
                        Task { await model.delete(zone: editable) }
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
