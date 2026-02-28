import Foundation

struct LegacyImportResult {
    let imported: Bool
    let legacyPythonRunning: Bool
}

enum LegacyConfigImporter {
    static func importIfNeeded(into store: AppGroupStore = .shared) -> LegacyImportResult {
        if store.migrationComplete {
            return LegacyImportResult(imported: false, legacyPythonRunning: isLegacyPythonAgentRunning())
        }

        let configDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/life-manager", isDirectory: true)
        let backendURL = configDir.appendingPathComponent("backend.url")
        let auth = configDir.appendingPathComponent("auth")

        if let urlString = try? String(contentsOf: backendURL, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines),
           let url = AppGroupStore.validatedCloudBackendURL(from: urlString) {
            store.backendURL = url
        } else {
            store.backendURL = nil
        }

        if let authString = try? String(contentsOf: auth, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !authString.isEmpty {
            store.authValue = authString
        }

        store.migrationComplete = true
        return LegacyImportResult(imported: true, legacyPythonRunning: isLegacyPythonAgentRunning())
    }

    static func isLegacyPythonAgentRunning() -> Bool {
        let patterns = [
            "menubar_app.py",
            "mac_client",
            "life_manager",
            "Python.app.*menubar_app.py",
            "Python.app.*mac_client",
        ]
        for pattern in patterns {
            if isPythonProcessRunning(pattern: pattern) {
                return true
            }
        }
        return false
    }

    private static func isPythonProcessRunning(pattern: String) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        process.arguments = ["-af", pattern]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()

        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(decoding: data, as: UTF8.self)
            return !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        } catch {
            return false
        }
    }

    static func killLegacyPythonAgent() {
        let patterns = [
            "menubar_app.py",
            "mac_client",
            "life_manager",
            "Python.app.*menubar_app.py",
            "Python.app.*mac_client",
        ]
        for pattern in patterns {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
            process.arguments = ["-f", pattern]
            try? process.run()
            process.waitUntilExit()
        }
    }
}
