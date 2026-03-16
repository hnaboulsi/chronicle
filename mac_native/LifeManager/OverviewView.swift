import SwiftUI

struct OverviewView: View {
    @EnvironmentObject private var model: NativeAppModel

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

                VStack(alignment: .leading, spacing: Spacing.md) {
                    SectionHeaderLabel("Recent Chat", icon: "bubble.left.and.bubble.right", color: .brand)
                        .padding(.horizontal, Spacing.lg)

                    if model.chatTurns.isEmpty {
                        HStack {
                            Spacer()
                            VStack(spacing: Spacing.sm) {
                                Image(systemName: "bubble.left.and.bubble.right")
                                    .font(.system(size: 28))
                                    .foregroundStyle(.secondary)
                                Text("No conversations yet")
                                    .foregroundStyle(.secondary)
                                    .font(.subheadline)
                            }
                            Spacer()
                        }
                        .padding(.vertical, 32)
                    } else {
                        VStack(spacing: Spacing.md) {
                            ForEach(Array(model.chatTurns.suffix(5).reversed()), id: \.self) { turn in
                                VStack(spacing: Spacing.xs) {
                                    ChatBubble(text: turn.user, isUser: true)
                                    ChatBubble(text: turn.reply, isUser: false)
                                    Text(turn.time)
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                        .frame(maxWidth: .infinity)
                                }
                            }
                        }
                        .padding(.horizontal, Spacing.lg)
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

    private func formatUptime(_ seconds: Int) -> String {
        let days = seconds / 86_400
        let hours = (seconds % 86_400) / 3600
        let minutes = (seconds % 3600) / 60
        if days > 0 {
            return "\(days)d \(hours)h"
        }
        if hours > 0 {
            return "\(hours)h \(minutes)m"
        }
        return "\(minutes)m"
    }

    @ViewBuilder
    private var summaryCards: some View {
        DashboardCard(
            title: "System Status",
            icon: "waveform.path.ecg",
            iconColor: .green,
            tint: healthColor(model.health?.status) == .green ? .greenTint : (healthColor(model.health?.status) == .orange ? .orangeTint : .redTint)
        ) {
            VStack(alignment: .leading, spacing: 10) {
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
            }
        }

        DashboardCard(
            title: "Current Activity",
            icon: "figure.walk",
            iconColor: .blue,
            tint: .blueTint
        ) {
            VStack(alignment: .leading, spacing: 10) {
                Text(model.state.current_activity_summary ?? model.state.current_activity_category ?? "Unknown")
                    .font(.system(.body, design: .rounded))
                    .fontWeight(.semibold)
                    .foregroundStyle(.primary)
                Text("Last capture \(ageString(model.state.last_mac_capture_age_seconds ?? model.state.last_mac_snapshot_age_seconds))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Divider()
                InfoRow(label: "Presence", value: presenceLabel(model.state.presence_state))
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
            VStack(alignment: .leading, spacing: 10) {
                Text(model.store.backendURL?.absoluteString ?? "Not configured")
                    .font(.system(.caption, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .foregroundStyle(.secondary)
                Divider()
                HStack {
                    Text("Last Heartbeat")
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(ageString(model.state.last_mac_heartbeat_age_seconds))
                        .font(.caption)
                }
                InfoRow(label: "Capture Interval", value: captureIntervalLabel(model.state.capture_interval_seconds))
                InfoRow(label: "Privacy", value: privacyModeLabel(model.state.privacy_mode))
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

    private func captureIntervalLabel(_ value: Int?) -> String {
        guard let value else { return "Unknown" }
        if value == 60 { return "1 minute" }
        if value == 300 { return "5 minutes" }
        if value == 900 { return "15 minutes" }
        return "\(value)s"
    }

    private func privacyModeLabel(_ value: String?) -> String {
        (value ?? "private") == "detailed" ? "Detailed Capture" : "Private by Default"
    }
}
