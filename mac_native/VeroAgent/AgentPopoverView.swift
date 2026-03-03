import SwiftUI
import AppKit

struct AgentPopoverView: View {
    @ObservedObject var store = AppGroupStore.shared

    var isConnected: Bool { store.helperLastError.isEmpty }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 12) {
                Image(systemName: "waveform.path.ecg")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(Color.indigo)

                VStack(alignment: .leading, spacing: 1) {
                    Text("Vero")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.primary)
                    Text("Activity Tracking")
                        .font(.system(size: 12, weight: .regular))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Circle()
                    .fill(isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                    .shadow(color: isConnected ? Color.green.opacity(0.5) : Color.clear, radius: 3)
            }
            .padding(.horizontal, 20)
            .frame(height: 56)
            .background(Color(NSColor.windowBackgroundColor))
            .overlay(alignment: .bottom) {
                Color.gray.opacity(0.2).frame(height: 1)
            }

            // Body content
            VStack(spacing: 14) {
                if !isConnected {
                    Text(store.helperLastError)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(10)
                        .frame(maxWidth: .infinity)
                        .background(Color.red.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                }

                Button(action: {
                    if let configuration = store.backendConfiguration {
                        let url = configuration.baseURL.appendingPathComponent("dashboard/index.html")
                        NSWorkspace.shared.open(url)
                    }
                }) {
                    HStack(spacing: 12) {
                        Image(systemName: "globe")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                            .frame(width: 20)
                        Text("Open Web Dashboard")
                            .font(.system(size: 13))
                            .foregroundStyle(.primary)
                        Spacer()
                        Image(systemName: "arrow.up.right")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(Color(NSColor.controlBackgroundColor))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)

                Button(action: {
                    if let url = URL(string: "vero://open") {
                        NSWorkspace.shared.open(url)
                    }
                }) {
                    HStack(spacing: 12) {
                        Image(systemName: "slider.horizontal.3")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                            .frame(width: 20)
                        Text("Open Vero Settings")
                            .font(.system(size: 13))
                            .foregroundStyle(.primary)
                        Spacer()
                        Image(systemName: "arrow.up.right")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(Color(NSColor.controlBackgroundColor))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)
                
                Button(action: {
                    store.trackingEnabled.toggle()
                }) {
                    HStack(spacing: 12) {
                        Image(systemName: store.trackingEnabled ? "pause.circle" : "play.circle")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                            .frame(width: 20)
                        Text(store.trackingEnabled ? "Pause Tracking" : "Resume Tracking")
                            .font(.system(size: 13))
                            .foregroundStyle(.primary)
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(Color(NSColor.controlBackgroundColor))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)

                Spacer(minLength: 10)

                Button(action: {
                    NSApplication.shared.terminate(nil)
                }) {
                    Text("Quit Vero")
                        .font(.system(size: 13))
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
            }
            .padding(20)
            
            Spacer(minLength: 0)
        }
        .frame(width: 320, height: 350)
        .background(Color(NSColor.windowBackgroundColor))
    }
}
