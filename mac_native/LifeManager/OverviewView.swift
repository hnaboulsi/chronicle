import SwiftUI

struct OverviewView: View {
    @EnvironmentObject private var model: NativeAppModel
    @Environment(\.openURL) private var openURL

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                VStack(spacing: Spacing.lg) {
                    if model.health == nil {
                        loadingCards
                    } else {
                        summaryCards
                    }
                }


            }
            .padding(Spacing.xl)
        }
        .navigationTitle("Overview")
    }

    private func ageString(_ value: Int?) -> String {
        guard let value else { return "Unknown" }
        if value < 60 { return "\(value)s ago" }
        if value < 3600 { return "\(value / 60)m ago" }
        if value < 86_400 { return "\(value / 3600)h ago" }
        return "\(value / 86_400)d ago"
    }


    @ViewBuilder
    private var summaryCards: some View {
        DashboardCard(
            title: "System Status",
            icon: "waveform.path.ecg",
            iconColor: .green,
            tint: healthColor(model.health?.status) == .green ? .greenTint : (healthColor(model.health?.status) == .orange ? .orangeTint : .redTint)
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                HStack {
                    StatusDot(
                        color: healthColor(model.health?.status),
                        label: model.health?.status.capitalized ?? "Unknown",
                        isPulsing: healthColor(model.health?.status) == .green
                    )
                    Spacer()
                    StatusBadge(
                        label: (model.state.mac_status ?? "unknown").replacingOccurrences(of: "_", with: " ").capitalized,
                        color: macStatusColor(model.state.mac_status)
                    )
                }
                Divider()
                InfoRow(label: "Detail", value: model.state.mac_status_reason ?? "Waiting for agent")
                InfoRow(label: "Uptime", value: formatUptime(model.health?.uptime_seconds ?? 0))
                if let backend = model.iosSetupPack?.backend_url, let url = URL(string: backend + "/setup/ios") {
                    HStack {
                        Text("iPhone Setup")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button(iosSetupLabel) {
                            openURL(url)
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
        }

        DashboardCard(
            title: "Current Activity",
            icon: "figure.walk",
            iconColor: .blue,
            tint: .blueTint
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(model.state.current_activity_summary ?? model.state.current_activity_category ?? "Unknown")
                    .font(.system(.body, design: .rounded))
                    .fontWeight(.semibold)
                    .foregroundStyle(.primary)
                Text("Last seen \(ageString(model.state.last_mac_snapshot_age_seconds))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Divider()
                InfoRow(label: "Location", value: model.state.current_location ?? "No recent data")
                InfoRow(label: "Sleep", value: model.state.sleep_status_note ?? "Unknown")
            }
        }

        DashboardCard(
            title: "Connection",
            icon: "network",
            iconColor: .indigo,
            tint: .indigoTint
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(model.store.backendURL?.absoluteString ?? "Not configured")
                    .font(.system(.caption, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .foregroundStyle(.secondary)
                Divider()
                HStack {
                    Text("Last Sync")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(ageString(model.state.last_mac_heartbeat_age_seconds))
                        .font(.caption)
                }
            }
        }
    }

    @ViewBuilder
    private var loadingCards: some View {
        ForEach(0 ..< 3, id: \.self) { _ in
            DashboardCard(
                title: "Loading",
                icon: "waveform.path.ecg",
                iconColor: .indigo,
                tint: .indigoTint
            ) {
                VStack(spacing: Spacing.sm) {
                    ShimmerView(height: 18, cornerRadius: 8)
                    ShimmerView(height: 14, cornerRadius: 8)
                    ShimmerView(height: 14, cornerRadius: 8)
                }
            }
        }
    }

    private var iosSetupLabel: String {
        let required = model.iosSetupStatus?.required ?? []
        if required.isEmpty { return "Set up" }
        let configured = required.filter { $0.configured == true }.count
        return configured == required.count ? "Ready" : "\(configured)/\(required.count)"
    }
}
