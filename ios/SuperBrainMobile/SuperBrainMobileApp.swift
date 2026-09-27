import SwiftUI
import LocalAuthentication

@main
struct SuperBrainMobileApp: App {
    @StateObject private var model = MissionStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
        }
    }
}

private struct RootView: View {
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("requireLocalAuth") private var requireLocalAuth = true
    @State private var unlocked = false
    @State private var authInProgress = false
    @State private var authError: String?

    var body: some View {
        ZStack {
            ContentView()

            if requireLocalAuth && !unlocked {
                Rectangle()
                    .fill(.ultraThinMaterial)
                    .ignoresSafeArea()

                VStack(spacing: 18) {
                    Image(systemName: "brain.head.profile.fill")
                        .font(.system(size: 58))
                    Text("SuperBrain is vergrendeld")
                        .font(.title2.bold())
                    Text("Ontgrendel met Face ID, Touch ID of je toestelcode.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                    if let authError {
                        Text(authError)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    Button {
                        authenticate()
                    } label: {
                        Label("Ontgrendel", systemImage: "faceid")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(authInProgress)
                }
                .padding(28)
            }
        }
        .task {
            if requireLocalAuth {
                authenticate()
            } else {
                unlocked = true
            }
        }
        .onChange(of: requireLocalAuth) { _, enabled in
            if enabled {
                unlocked = false
                authenticate()
            } else {
                unlocked = true
                authError = nil
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background && requireLocalAuth {
                unlocked = false
            } else if phase == .active && requireLocalAuth && !unlocked {
                authenticate()
            }
        }
    }

    private func authenticate() {
        guard requireLocalAuth, !unlocked, !authInProgress else { return }

        let context = LAContext()
        context.localizedCancelTitle = "Annuleer"
        var evaluationError: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &evaluationError) else {
            authError = evaluationError?.localizedDescription ?? "Lokale toestelbeveiliging is niet beschikbaar."
            return
        }

        authInProgress = true
        authError = nil
        context.evaluatePolicy(.deviceOwnerAuthentication,
                               localizedReason: "Ontgrendel SuperBrain") { success, error in
            DispatchQueue.main.async {
                authInProgress = false
                unlocked = success
                if !success {
                    authError = error?.localizedDescription ?? "Ontgrendelen is geannuleerd."
                }
            }
        }
    }
}
