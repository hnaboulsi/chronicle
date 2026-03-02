import SwiftUI

struct ZonesView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) private var openURL
    @State private var showingAddZone = false
    @State private var pendingDeleteZone: ZoneRecord?
    @State private var showDeleteConfirmation = false

    var body: some View {
        List {
            Section {
                HStack {
                    Text("Required automations")
                    Spacer()
                    Text(requiredStatus)
                        .foregroundStyle(requiredReady ? .green : .orange)
                }
                if let backend = model.iosSetupPack?.backend_url, let url = URL(string: backend + "/setup/ios") {
                    Button("Open Web iPhone Setup") {
                        openURL(url)
                    }
                }
            } header: {
                Text("iPhone Automation Status")
            } footer: {
                Text("Zone setup is web-first. This app manages zones only.")
            }

            if !model.zones.isEmpty {
                Section {
                    ForEach(model.zones, id: \.self) { zone in
                        NavigationLink(value: zone) {
                            ZoneRowView(zone: zone)
                        }
                    }
                    .onDelete { indices in
                        guard let index = indices.first else { return }
                        pendingDeleteZone = model.zones[index]
                        showDeleteConfirmation = true
                    }
                } header: {
                    Text("Your Zones")
                } footer: {
                    Text("Swipe left on a zone to delete it.")
                }
            }
        }
        .listStyle(.inset)
        .animation(.easeInOut, value: model.zones)
        .navigationTitle("Zones")
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button(action: { showingAddZone = true }) {
                    Label("Add Zone", systemImage: "plus")
                }
            }
        }
        .sheet(isPresented: $showingAddZone) {
            ZoneEditorSheet(zone: .empty, isNew: true)
                .environmentObject(model)
        }
        .navigationDestination(for: ZoneRecord.self) { zone in
            ZoneEditorSheet(zone: zone, isNew: false)
                .environmentObject(model)
        }
        .confirmationDialog("Delete this zone?", isPresented: $showDeleteConfirmation, presenting: pendingDeleteZone) { zone in
            Button("Delete \"\(zone.name)\"", role: .destructive) {
                Task {
                    _ = await model.delete(zone: zone)
                    pendingDeleteZone = nil
                }
            }
            Button("Cancel", role: .cancel) {
                pendingDeleteZone = nil
            }
        } message: { zone in
            Text("Are you sure you want to delete \"\(zone.name)\"?")
        }
    }

    private var requiredReady: Bool {
        let required = model.iosSetupStatus?.required ?? []
        guard !required.isEmpty else { return false }
        return required.allSatisfy { $0.configured == true }
    }

    private var requiredStatus: String {
        let required = model.iosSetupStatus?.required ?? []
        if required.isEmpty { return "Not configured" }
        let configured = required.filter { $0.configured == true }.count
        return "\(configured)/\(required.count)"
    }
}

private struct ZoneRowView: View {
    let zone: ZoneRecord

    var body: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: zoneTypeIcon(zone.zone_type).0)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(zoneTypeIcon(zone.zone_type).1)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(zone.name)
                    .font(.subheadline.weight(.semibold))
                Text("\(zone.radius_meters)m radius")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if zone.is_default ?? false {
                StatusBadge(label: "Default", color: .blue)
            }

            StatusBadge(label: zone.enabled ? "On" : "Off", color: zone.enabled ? .green : .orange)
        }
    }
}

private struct ZoneEditorSheet: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.dismiss) private var dismiss
    @State private var editable: ZoneRecord
    @State private var showDeleteConfirmation = false
    @State private var saved = false

    init(zone: ZoneRecord, isNew: Bool) {
        _editable = State(initialValue: zone)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Basic Info") {
                    TextField("Name", text: $editable.name)
                    TextField("Slug", text: $editable.slug)
                        .disabled(editable.is_default ?? false)
                    Toggle("Enabled", isOn: $editable.enabled)
                }

                Section("Geofence") {
                    Picker("Type", selection: $editable.zone_type) {
                        Text("Home").tag("home")
                        Text("Lecture").tag("lecture")
                        Text("Study").tag("study")
                        Text("Gym").tag("gym")
                        Text("Custom").tag("custom")
                    }
                    Stepper(value: $editable.radius_meters, in: 25 ... 500, step: 5) {
                        HStack {
                            Text("Radius")
                            Spacer()
                            Text("\(editable.radius_meters)m")
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                Section {
                    TextField("Focus Hint (optional)", text: $editable.focus_mode)
                } header: {
                    Text("Focus Mode")
                } footer: {
                    Text("Used to identify which Focus mode matches this zone.")
                }

                Section("Payloads") {
                    VStack(alignment: .leading, spacing: Spacing.sm) {
                        Text("Entry")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("{\"zone_slug\":\"\(editable.slug)\",\"transition\":\"enter\"}")
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                        Divider()
                        Text("Exit")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text("{\"zone_slug\":\"\(editable.slug)\",\"transition\":\"exit\"}")
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Button("Delete Zone", role: .destructive) {
                        showDeleteConfirmation = true
                    }
                }

                if saved {
                    Section {
                        Text("Saved ✓")
                            .foregroundStyle(.green)
                            .font(.subheadline.weight(.semibold))
                    }
                }
            }
            .navigationTitle(editable.id == nil ? "New Zone" : editable.name)
            .toolbar {
                ToolbarItemGroup(placement: .confirmationAction) {
                    Button("Save") {
                        Task {
                            guard await model.save(zone: editable) else { return }
                            withAnimation(.easeInOut(duration: 0.2)) {
                                saved = true
                            }
                            try? await Task.sleep(for: .milliseconds(800))
                            dismiss()
                        }
                    }
                    .disabled(editable.name.isEmpty || editable.slug.isEmpty)
                }
            }
            .confirmationDialog("Delete this zone?", isPresented: $showDeleteConfirmation) {
                Button("Delete \"\(editable.name)\"", role: .destructive) {
                    Task {
                        guard await model.delete(zone: editable) else { return }
                        dismiss()
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Are you sure you want to delete \"\(editable.name)\"?")
            }
        }
    }
}
