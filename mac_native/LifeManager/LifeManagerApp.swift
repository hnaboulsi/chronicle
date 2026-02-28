import SwiftUI

@main
struct LifeManagerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = NativeAppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 980, minHeight: 700)
                .task {
                    await model.startup()
                }
                .onOpenURL { url in
                    model.handle(url: url)
                }
        }
    }
}
