import Foundation
import ServiceManagement

final class HelperController {
    static let shared = HelperController()

    private init() {}

    var actualStatus: String {
        if #available(macOS 13.0, *) {
            let service = SMAppService.loginItem(identifier: AppConstants.agentBundleIdentifier)
            switch service.status {
            case .enabled:
                return "running"
            case .requiresApproval:
                return "needs approval"
            case .notRegistered:
                return "not installed"
            case .notFound:
                return "not found"
            @unknown default:
                return "unknown"
            }
        }
        return "unknown"
    }

    func ensureHelperEnabled() {
        if #available(macOS 13.0, *) {
            let service = SMAppService.loginItem(identifier: AppConstants.agentBundleIdentifier)
            if service.status != .enabled {
                try? service.register()
            }
        }
        AppGroupStore.shared.helperDesiredState = "enabled"
    }

    func disableHelper() {
        if #available(macOS 13.0, *) {
            let service = SMAppService.loginItem(identifier: AppConstants.agentBundleIdentifier)
            try? service.unregister()
        }
        AppGroupStore.shared.helperDesiredState = "disabled"
    }

    func repairHelper() {
        disableHelper()
        ensureHelperEnabled()
    }
}
