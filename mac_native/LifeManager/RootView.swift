import SwiftUI

struct RootView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedScreen) {
                Section("Status") {
                    Label("Overview", systemImage: "waveform.path.ecg")
                        .tag(AppScreen.overview)
                    Label("Tracking", systemImage: "dial.high")
                        .tag(AppScreen.tracking)
                    Label("Zones", systemImage: "location")
                        .tag(AppScreen.zones)
                }
                Section("System") {
                    Label("Permissions", systemImage: "lock.shield")
                        .tag(AppScreen.permissions)
                    Label("Diagnostics", systemImage: "wrench.and.screwdriver")
                        .tag(AppScreen.diagnostics)
                    Label("Calendar", systemImage: "calendar")
                        .tag(AppScreen.calendar)
                }
            }
            .listStyle(.sidebar)
        } detail: {
            detailView
        }
        .toolbar {
            ToolbarItemGroup {
                Button("Refresh") {
                    Task { await model.refreshAll() }
                }
                Button("Open Web Dashboard") {
                    model.openWebDashboard()
                }
            }
        }
        .overlay(alignment: .bottomLeading) {
            if !model.statusMessage.isEmpty {
                Text(model.statusMessage)
                    .font(.caption)
                    .padding(10)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
                    .padding()
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
        }
    }
}
