import SwiftUI

@main
struct SuperBrainMobileApp: App {
    @StateObject private var model = MissionStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}
