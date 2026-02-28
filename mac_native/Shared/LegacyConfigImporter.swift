import Foundation

struct LegacyImportResult {
    let imported: Bool
    let legacyPythonRunning: Bool
}

enum LegacyConfigImporter {
    static func migrateAppGroupIfNeeded() {
        let newSuite = UserDefaults(suiteName: AppConstants.appGroupIdentifier)!
        guard newSuite.bool(forKey: "app_group_migrated") == false else { return }
        guard let oldSuite = UserDefaults(suiteName: "group.com.naboulsi.lifemanager") else {
            newSuite.set(true, forKey: "app_group_migrated")
            return
        }

        let keysToMigrate = [
            "backend_url", "auth_value", "tracking_enabled", "ai_provider",
            "notification_level", "polling_interval_seconds", "classification_interval_seconds",
            "migration_complete", "helper_desired_state", "helper_last_error",
            "helper_last_seen_at", "legacy_python_warning_shown", "client_id"
        ]
        for key in keysToMigrate {
            if let value = oldSuite.object(forKey: key) {
                newSuite.set(value, forKey: key)
            }
        }
        newSuite.set(true, forKey: "app_group_migrated")
    }

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
