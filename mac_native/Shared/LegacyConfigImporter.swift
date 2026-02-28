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
           let url = URL(string: urlString),
           !urlString.isEmpty {
            store.backendURL = url
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
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        process.arguments = ["-af", "menubar_app.py"]
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
}
