import SwiftUI

struct SetupView: View {
    @State private var backendURLInput = ""
    @State private var authTokenInput = ""
    @State private var isLoading = false
    @State private var errorMessage = ""
    @State private var showError = false
    @State private var successMessage = ""
    let onConnected: () -> Void

    var body: some View {
        ZStack {
            // Gradient background
            LinearGradient(
                gradient: Gradient(colors: [
                    Color.indigo.opacity(0.1),
                    Color.blue.opacity(0.05)
                ]),
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            VStack(spacing: 32) {
                // Header
                VStack(spacing: 12) {
                    Image(systemName: "waveform.path.ecg")
                        .font(.system(size: 48, weight: .semibold))
                        .foregroundStyle(Color.indigo)

                    Text("Vero")
                        .font(.system(size: 32, weight: .bold))
                        .foregroundStyle(.primary)

                    Text("Connect the menu bar companion to your hosted backend")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                // Form
                VStack(spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Backend URL", systemImage: "cloud.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color.indigo)

                        TextField("https://your-backend.example.com", text: $backendURLInput)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))
                            .autocorrectionDisabled()

                        Text("Must be an HTTPS URL to your cloud backend")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Label("Password / Basic Auth", systemImage: "key.fill")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Color.indigo)

                        SecureField("Paste the dashboard password or basic-auth value", text: $authTokenInput)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))

                        Text("Use the same password or HTTP Basic Auth value that protects your hosted Vero dashboard.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    if showError && !errorMessage.isEmpty {
                        HStack(spacing: 8) {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(.red)
                            Text(errorMessage)
                                .font(.caption)
                                .foregroundStyle(.red)
                        }
                        .padding(.vertical, 10)
                        .padding(.horizontal, 12)
                        .background(Color.red.opacity(0.1))
                        .cornerRadius(8)
                    }

                    if !successMessage.isEmpty {
                        HStack(spacing: 8) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Text(successMessage)
                                .font(.caption)
                                .foregroundStyle(.green)
                        }
                        .padding(.vertical, 10)
                        .padding(.horizontal, 12)
                        .background(Color.green.opacity(0.1))
                        .cornerRadius(8)
                    }
                }
                .padding(20)
                .background(Color.white.opacity(0.7))
                .cornerRadius(12)

                VStack(alignment: .leading, spacing: 10) {
                    Label("What happens next", systemImage: "checkmark.seal")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.indigo)
                    Text("After saving the connection, Vero continues from your menu bar. Use the dashboard for settings, privacy, zones, and diagnostics.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .background(Color.white.opacity(0.6))
                .cornerRadius(12)

                // Connect Button
                Button(action: connectToBackend) {
                    if isLoading {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Label("Connect Menu Bar Companion", systemImage: "network")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(12)
                .background(Color.indigo)
                .foregroundStyle(.white)
                .cornerRadius(8)
                .font(.subheadline.weight(.semibold))
                .disabled(isLoading || backendURLInput.isEmpty || authTokenInput.isEmpty)
                .opacity(isLoading || backendURLInput.isEmpty || authTokenInput.isEmpty ? 0.6 : 1.0)
            }
            .padding(40)
            .frame(maxWidth: 500)
        }
        .frame(minWidth: 600, minHeight: 700)
        .onAppear(perform: preloadExistingConfiguration)
    }

    private func connectToBackend() {
        errorMessage = ""
        showError = false
        successMessage = ""
        isLoading = true

        let trimmedURL = backendURLInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = AppGroupStore.validatedCloudBackendURL(from: trimmedURL) else {
            errorMessage = "Invalid URL. Must be HTTPS (e.g., https://your-backend.example.com)"
            showError = true
            isLoading = false
            return
        }

        let auth = authTokenInput.trimmingCharacters(in: .whitespacesAndNewlines)
        if auth.isEmpty {
            errorMessage = "Password or basic-auth value is required"
            showError = true
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
                    successMessage = "Connection saved. Opening the dashboard."
                    NSWorkspace.shared.open(url.appendingPathComponent("today"))
                    isLoading = false
                    onConnected()
                }
            } catch {
                await MainActor.run {
                    errorMessage = "Failed to connect: \(error.localizedDescription)"
                    showError = true
                    isLoading = false
                }
            }
        }
    }

    private func preloadExistingConfiguration() {
        guard backendURLInput.isEmpty, authTokenInput.isEmpty else {
            return
        }

        let store = AppGroupStore.shared
        if let configuration = store.backendConfiguration {
            backendURLInput = configuration.baseURL.absoluteString
            authTokenInput = configuration.authValue
        }
    }
}

#Preview {
    SetupView(onConnected: {})
}
