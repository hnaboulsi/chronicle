import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var displayedStatusMessage = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    Text("Vero lives in your menu bar")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                    Text("Use the dashboard for settings, privacy, zones, and diagnostics. The Mac app just keeps the menu bar companion connected and gives you quick recovery actions.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Close this window any time. Tracking continues from the menu bar helper.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }

                DashboardCard(
                    title: "Menu Bar Companion",
                    icon: "menubar.rectangle",
                    iconColor: .brand,
                    tint: .indigoTint
                ) {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            StatusDot(
                                color: macStatusColor(model.state.mac_status),
                                label: (model.state.mac_status ?? "unknown").replacingOccurrences(of: "_", with: " ").capitalized,
                                isPulsing: model.state.mac_status == "online"
                            )
                            Spacer()
                            StatusBadge(
                                label: model.helperDesiredState.capitalized,
                                color: model.helperDesiredState == "enabled" ? .green : .orange
                            )
                        }
                        Divider()
                        InfoRow(label: "Backend", value: backendLabel)
                        InfoRow(label: "Tracking", value: model.settings.tracking_enabled ? "Enabled" : "Paused")
                        InfoRow(label: "Last heartbeat", value: ageString(model.state.last_mac_heartbeat_age_seconds))
                        InfoRow(label: "Last capture", value: ageString(model.state.last_mac_capture_age_seconds))
                    }
                }

                DashboardCard(
                    title: "Live Status",
                    icon: "waveform.path.ecg",
                    iconColor: .green,
                    tint: .greenTint
                ) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text(model.state.current_activity_summary ?? "Waiting for the next capture")
                            .font(.system(.body, design: .rounded))
                            .fontWeight(.semibold)
                        Divider()
                        InfoRow(label: "Presence", value: presenceLabel(model.state.presence_state))
                        InfoRow(label: "Capture cadence", value: captureIntervalLabel(model.settings.capture_interval_seconds))
                        InfoRow(label: "Privacy", value: privacyModeLabel(model.settings.privacy_mode))
                        InfoRow(label: "Helper issue", value: model.helperLastError.isEmpty ? "None" : model.helperLastError, color: model.helperLastError.isEmpty ? nil : .red)
                    }
                }

                DashboardCard(
                    title: "Where To Go",
                    icon: "globe",
                    iconColor: .blue,
                    tint: .blueTint
                ) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Dashboard is the source of truth")
                            .font(.subheadline.weight(.semibold))
                        Text("Change tracking cadence, privacy mode, AI limits, zones, and diagnostics in the hosted dashboard. Use this Mac window only when you need to reconnect the menu bar companion or fix local permissions.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: Spacing.md) {
                    Button(action: { model.openWebDashboard() }) {
                        Label("Open Dashboard", systemImage: "globe")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)

                    Button(action: { model.openWebDashboard(path: "/settings") }) {
                        Label("Dashboard Settings", systemImage: "slider.horizontal.3")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)

                    Button(action: { model.openMacSetupGuide() }) {
                        Label("Mac Setup Guide", systemImage: "hammer")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)

                    Button(action: { model.openSystemSettings() }) {
                        Label("System Settings", systemImage: "gear")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }

                HStack(spacing: Spacing.md) {
                    Button(action: { model.repairHelper() }) {
                        Label("Repair Helper", systemImage: "wrench.and.screwdriver")
                    }
                    .buttonStyle(.bordered)

                    Button(action: { Task { await model.refreshAll() } }) {
                        Label("Refresh Status", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding(Spacing.xl)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .overlay(alignment: .bottomLeading) {
            if !displayedStatusMessage.isEmpty {
                Text(displayedStatusMessage)
                    .font(.caption)
                    .padding(10)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .strokeBorder(Color.indigo.opacity(0.3), lineWidth: 1)
                    )
                    .padding()
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button(action: { model.openWebDashboard() }) {
                    Label("Dashboard", systemImage: "globe")
                }
                Button(action: { Task { await model.refreshAll() } }) {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
        .onAppear {
            displayedStatusMessage = model.statusMessage
        }
        .onChange(of: model.statusMessage) { newValue in
            withAnimation(.easeInOut(duration: 0.25)) {
                displayedStatusMessage = newValue
            }
        }
    }

    private var backendLabel: String {
        if let target = model.state.backend_target_url,
           let url = URL(string: target),
           let host = url.host {
            return host
        }
        if let host = model.store.backendURL?.host {
            return host
        }
        return "Not configured"
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

    private func captureIntervalLabel(_ value: Int) -> String {
        if value == 60 { return "1 minute" }
        if value == 300 { return "5 minutes" }
        if value == 900 { return "15 minutes" }
        return "\(value)s"
    }

    private func privacyModeLabel(_ value: String) -> String {
        value == "detailed" ? "Detailed Capture" : "Private by Default"
    }
}
