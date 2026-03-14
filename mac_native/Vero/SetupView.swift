import SwiftUI

struct SetupView: View {
    @State private var backendURLInput = ""
    @State private var authTokenInput = ""
    @State private var isLoading = false
    @State private var errorMessage = ""
    @State private var statusMessage = ""
    let onConnected: () -> Void

    var body: some View {
        Form {
            Section("Connection") {
                TextField("Backend URL", text: $backendURLInput)
                    .autocorrectionDisabled()

                SecureField("Password or auth token", text: $authTokenInput)

                HStack {
                    Button(isLoading ? "Connecting…" : "Save Connection") {
                        connectToBackend()
                    }
                    .disabled(isLoading || backendURLInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || authTokenInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                    if let dashboardURL = dashboardURL {
                        Button("Open Dashboard") {
                            NSWorkspace.shared.open(dashboardURL)
                        }
                    }
                }

                Text("Use your deployed HTTPS backend URL and the same dashboard password the Mac app uses for Basic Auth.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Status") {
                LabeledContent("Connected", value: AppGroupStore.shared.isConfigured ? "Yes" : "No")
                LabeledContent("Calendar", value: CalendarSyncEngine.shared.targetDescription())
                Text(CalendarSyncEngine.shared.setupRecommendation())
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if !statusMessage.isEmpty {
                Section {
                    Text(statusMessage)
                        .foregroundStyle(.green)
                }
            }

            if !errorMessage.isEmpty {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                }
            }
        }
        .formStyle(.grouped)
        .padding(12)
        .onAppear(perform: preloadExistingConfiguration)
    }

    private var dashboardURL: URL? {
        AppGroupStore.shared.backendURL?.appendingPathComponent("dashboard/index.html")
    }

    private func connectToBackend() {
        errorMessage = ""
        statusMessage = ""
        isLoading = true

        let trimmedURL = backendURLInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = AppGroupStore.validatedCloudBackendURL(from: trimmedURL) else {
            errorMessage = "Enter a valid HTTPS backend URL."
            isLoading = false
            return
        }

        let auth = authTokenInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !auth.isEmpty else {
            errorMessage = "Enter the dashboard password or auth token."
            isLoading = false
            return
        }

        let configuration = BackendConfiguration(baseURL: url, authValue: auth)

        Task {
            do {
                let client = BackendClient(configuration: configuration)
                _ = try await client.fetchHealth()

                await MainActor.run {
                    let store = AppGroupStore.shared
                    store.backendURL = url
                    store.authValue = auth
                    statusMessage = "Connection saved."
                    isLoading = false
                    onConnected()
                }
            } catch {
                await MainActor.run {
                    errorMessage = "Failed to connect: \(error.localizedDescription)"
                    isLoading = false
                }
            }
        }
    }

    private func preloadExistingConfiguration() {
        guard backendURLInput.isEmpty, authTokenInput.isEmpty else {
            return
        }

        if let configuration = AppGroupStore.shared.backendConfiguration {
            backendURLInput = configuration.baseURL.absoluteString
            authTokenInput = configuration.authValue
        }
    }
}

#Preview {
    SetupView(onConnected: {})
        .frame(width: 480, height: 320)
}
