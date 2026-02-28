import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: NativeAppModel
    @State private var displayedStatusMessage = ""

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    HStack(spacing: Spacing.sm) {
                        Image(systemName: "waveform.path.ecg")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(.indigo)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Vero")
                                .font(.headline)
                            Text("Cloud Agent")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.horizontal, Spacing.lg)
                    .padding(.top, Spacing.lg)
                    .padding(.bottom, Spacing.md)
                }

                List(selection: $model.selectedScreen) {
                    Section("Status") {
                        NavigationLink(value: AppScreen.overview) {
                            Label("Overview", systemImage: "waveform.path.ecg")
                        }
                        NavigationLink(value: AppScreen.tracking) {
                            Label("Tracking", systemImage: "dial.high")
                        }
                        NavigationLink(value: AppScreen.zones) {
                            Label("Zones", systemImage: "location")
                        }
                        NavigationLink(value: AppScreen.chat) {
                            Label("Chat", systemImage: "bubble.left.and.bubble.right.fill")
                        }
                    }
                    Section("System") {
                        NavigationLink(value: AppScreen.permissions) {
                            Label("Permissions", systemImage: "lock.shield")
                        }
                        NavigationLink(value: AppScreen.diagnostics) {
                            HStack {
                                Label("Diagnostics", systemImage: "wrench.and.screwdriver")
                                Spacer()
                                if !model.helperLastError.isEmpty {
                                    StatusBadge(label: "Issue", color: .red)
                                }
                            }
                        }
                        NavigationLink(value: AppScreen.calendar) {
                            HStack {
                                Label("Calendar", systemImage: "calendar")
                                Spacer()
                                if model.calendarJobs.count > 0 {
                                    StatusBadge(label: "\(model.calendarJobs.count)", color: .indigo)
                                }
                            }
                        }
                        NavigationLink(value: AppScreen.iphone) {
                            Label("iPhone Setup", systemImage: "iphone")
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        } detail: {
            detailView
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button(action: { Task { await model.refreshAll() } }) {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .help("Refresh all data")

                Button(action: { model.openWebDashboard() }) {
                    Label("Web Dashboard", systemImage: "globe")
                }
                .help("Open web dashboard in browser")
            }
        }
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
        .onAppear {
            displayedStatusMessage = model.statusMessage
        }
        .onChange(of: model.statusMessage) { newValue in
            withAnimation(.easeInOut(duration: 0.25)) {
                displayedStatusMessage = newValue
            }
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch model.selectedScreen {
        case .overview:
            OverviewView()
        case .tracking:
            TrackingView()
        case .zones:
            ZonesView()
        case .permissions:
            PermissionsView()
        case .diagnostics:
            DiagnosticsView()
        case .calendar:
            CalendarView()
        case .iphone:
            iPhoneSetupView()
        case .chat:
            ChatView()
        }
    }
}
