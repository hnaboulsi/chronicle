import SwiftUI

struct PermissionsView: View {
    @EnvironmentObject private var model: NativeAppModel

    var body: some View {
        Form {
            LabeledContent("Accessibility") {
                Text(model.permissionSnapshot.accessibility)
            }
            LabeledContent("Notifications") {
                Text(model.permissionSnapshot.notifications)
            }
            LabeledContent("Calendar") {
                Text(model.permissionSnapshot.calendar)
            }
            Button("Open Accessibility Settings") {
                model.openSystemSettings()
            }
            Button("Refresh Permissions") {
                Task {
                    model.permissionSnapshot = await PermissionSnapshot.capture()
                }
            }
        }
        .formStyle(.grouped)
        .padding(24)
    }
}
