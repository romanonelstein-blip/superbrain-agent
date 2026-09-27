import AVFoundation
import Foundation
import Speech

@MainActor
final class VoiceControl: ObservableObject {
    enum Command {
        case refresh
        case openSettings
        case mission(text: String, research: Bool)
        case draft(String)
    }

    @Published var transcript = ""
    @Published var isListening = false
    @Published var error: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "nl-NL"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var tapInstalled = false

    func toggle() async {
        if isListening {
            stop()
            return
        }
        await start()
    }

    func start() async {
        guard !isListening else { return }
        error = nil

        let speechAllowed = await requestSpeechAuthorization()
        guard speechAllowed else {
            error = "Geef SuperBrain toegang tot spraakherkenning om voice control te gebruiken."
            return
        }

        let microphoneAllowed = await requestMicrophoneAuthorization()
        guard microphoneAllowed else {
            error = "Geef SuperBrain microfoontoegang om voice control te gebruiken."
            return
        }

        guard let recognizer, recognizer.isAvailable else {
            error = "Spraakherkenning is op dit moment niet beschikbaar."
            return
        }

        stop(clearTranscript: false)
        transcript = ""

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            self.error = "De microfoon kon niet worden gestart."
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        recognitionRequest = request

        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }
        tapInstalled = true

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    if result.isFinal {
                        self.stop(clearTranscript: false)
                    }
                }
                if error != nil && self.isListening {
                    self.error = "Spraakherkenning is gestopt. Probeer het opnieuw."
                    self.stop(clearTranscript: false)
                }
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
        } catch {
            self.error = "De microfoon kon niet worden gestart."
            stop(clearTranscript: false)
        }
    }

    func stop(clearTranscript: Bool = false) {
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = nil

        if audioEngine.isRunning {
            audioEngine.stop()
        }
        if tapInstalled {
            audioEngine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        isListening = false
        if clearTranscript { transcript = "" }
    }

    func command(from rawText: String) -> Command? {
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        let normalized = text.lowercased()

        if normalized == "vernieuw" || normalized.contains("vernieuw status") || normalized == "refresh" {
            return .refresh
        }
        if normalized.contains("open instellingen") || normalized == "instellingen" {
            return .openSettings
        }

        let researchPrefixes = ["onderzoek ", "start onderzoek ", "research "]
        for prefix in researchPrefixes where normalized.hasPrefix(prefix) {
            let start = text.index(text.startIndex, offsetBy: min(prefix.count, text.count))
            let mission = String(text[start...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if !mission.isEmpty { return .mission(text: mission, research: true) }
        }

        let askPrefixes = ["vraag ", "vraag superbrain ", "superbrain "]
        for prefix in askPrefixes where normalized.hasPrefix(prefix) {
            let start = text.index(text.startIndex, offsetBy: min(prefix.count, text.count))
            let mission = String(text[start...]).trimmingCharacters(in: .whitespacesAndNewlines)
            if !mission.isEmpty { return .mission(text: mission, research: false) }
        }

        return .draft(text)
    }

    private func requestSpeechAuthorization() async -> Bool {
        if SFSpeechRecognizer.authorizationStatus() == .authorized { return true }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    private func requestMicrophoneAuthorization() async -> Bool {
        if #available(iOS 17.0, *) {
            return await AVAudioApplication.requestRecordPermission()
        }
        return false
    }
}
