import AppIntents
import Foundation

struct OpenSuperBrainIntent: AppIntent {
    static var title: LocalizedStringResource = "Open SuperBrain"
    static var description = IntentDescription("Open de SuperBrain cockpit.")
    static var openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        .result(dialog: "SuperBrain wordt geopend.")
    }
}

struct NewSuperBrainMissionIntent: AppIntent {
    static var title: LocalizedStringResource = "Nieuwe SuperBrain opdracht"
    static var description = IntentDescription("Zet een gesproken of getypte opdracht klaar in SuperBrain.")
    static var openAppWhenRun = true

    @Parameter(title: "Opdracht")
    var mission: String

    @Parameter(title: "Onderzoek met bronnen", default: false)
    var research: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Zet \(.$mission) klaar") {
            \.$research
        }
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let clean = mission.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return .result(dialog: "Ik heb nog een opdracht nodig.")
        }

        UserDefaults.standard.set(clean, forKey: "pendingShortcutMission")
        UserDefaults.standard.set(research, forKey: "pendingShortcutResearch")
        return .result(dialog: "De opdracht staat klaar in SuperBrain.")
    }
}

struct SuperBrainShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: OpenSuperBrainIntent(),
            phrases: [
                "Open \(.applicationName)",
                "Start \(.applicationName)"
            ],
            shortTitle: "Open SuperBrain",
            systemImageName: "brain.head.profile"
        )

        AppShortcut(
            intent: NewSuperBrainMissionIntent(),
            phrases: [
                "Nieuwe opdracht in \(.applicationName)",
                "Vraag \(.applicationName)"
            ],
            shortTitle: "Nieuwe opdracht",
            systemImageName: "waveform.and.mic"
        )
    }
}
