import SwiftUI

struct SuperBrainDashboard: View {
    @EnvironmentObject private var store: MissionStore
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var voice = VoiceControl()
    @State private var showSettings = false
    @State private var showRealityFork = false
    @State private var question = ""
    @State private var research = false

    var body: some View {
        NavigationStack {
            ZStack {
                SuperBrainBackground()

                ScrollView {
                    LazyVStack(spacing: 18) {
                        header

                        if store.address.isEmpty {
                            disconnectedCard
                        } else {
                            nexusHero
                            metrics
                            realityForkCard
                            voiceCard
                            missionComposer

                            if let response = store.latestResponse {
                                latestResponseCard(response)
                            }

                            missionsCard
                        }
                    }
                    .padding(.horizontal, SuperBrainTheme.pagePadding)
                    .padding(.top, 12)
                    .padding(.bottom, 40)
                }
                .refreshable { await store.refresh() }
            }
            .navigationBarHidden(true)
            .navigationDestination(for: String.self) { MissionDetailView(id: $0) }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(isPresented: $showRealityFork) { RealityForkSheet(seed: question) }
            .task {
                consumeShortcutMission()
                if !store.address.isEmpty {
                    await store.refresh()
                } else {
                    showSettings = true
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { consumeShortcutMission() }
            }
            .alert("SuperBrain", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
                Button("OK") { store.error = nil }
            } message: {
                Text(store.error ?? "")
            }
            .alert("Voice Control", isPresented: Binding(get: { voice.error != nil }, set: { if !$0 { voice.error = nil } })) {
                Button("OK") { voice.error = nil }
            } message: {
                Text(voice.error ?? "")
            }
        }
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(SuperBrainTheme.accent)
                    .frame(width: 46, height: 46)
                Image(systemName: "brain.head.profile.fill")
                    .font(.title3.bold())
                    .foregroundStyle(.white)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("SUPERBRAIN")
                    .font(.caption.weight(.heavy))
                    .tracking(2.4)
                    .foregroundStyle(.secondary)
                Text("Mission Control")
                    .font(.title2.bold())
                    .foregroundStyle(.white)
            }

            Spacer()

            Button {
                showSettings = true
            } label: {
                Image(systemName: "slider.horizontal.3")
                    .font(.headline)
                    .frame(width: 42, height: 42)
                    .background(.ultraThinMaterial, in: Circle())
                    .overlay { Circle().stroke(.white.opacity(0.10), lineWidth: 1) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Instellingen")
        }
    }

    private var disconnectedCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Image(systemName: "network.slash")
                .font(.system(size: 34))
                .foregroundStyle(.secondary)
            Text("Verbind je SuperBrain")
                .font(.title2.bold())
                .foregroundStyle(.white)
            Text("Voeg je beveiligde Mission Control-adres en toegangstoken toe om de cockpit te activeren.")
                .foregroundStyle(.secondary)
            Button("Open instellingen") { showSettings = true }
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .superBrainGlassCard()
    }

    private var nexusHero: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 7) {
                    Text("NEXUS-1000")
                        .font(.caption.weight(.bold))
                        .tracking(1.5)
                        .foregroundStyle(.secondary)
                    Text(store.status?.canonicalRuntime ?? "Runtime verbinden…")
                        .font(.title.bold())
                        .foregroundStyle(.white)
                        .lineLimit(2)
                }
                Spacer()
                ZStack {
                    Circle()
                        .stroke(.white.opacity(0.08), lineWidth: 8)
                    Circle()
                        .trim(from: 0, to: store.status == nil ? 0.18 : 0.86)
                        .stroke(SuperBrainTheme.accent, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Image(systemName: store.status == nil ? "bolt.horizontal.circle" : "checkmark.shield.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                }
                .frame(width: 72, height: 72)
            }

            HStack(spacing: 8) {
                StatusChip(title: store.status == nil ? "Offline" : "Connected",
                           systemImage: store.status == nil ? "wifi.slash" : "antenna.radiowaves.left.and.right",
                           active: store.status != nil)
                StatusChip(title: store.status?.researchMissionsAvailable == true ? "Research ready" : "Research gated",
                           systemImage: "checkmark.seal",
                           active: store.status?.researchMissionsAvailable == true)
            }

            if let missing = store.status?.missingRequiredMobileCapabilities, !missing.isEmpty {
                Label("Sync vereist: \(missing.joined(separator: ", "))", systemImage: "arrow.triangle.2.circlepath")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .superBrainGlassCard(padding: 20)
    }

    private var metrics: some View {
        HStack(spacing: 10) {
            MetricTile(value: "\(store.missions.count)", label: "Missions", systemImage: "scope")
            MetricTile(value: store.status?.apiVersion ?? SuperBrainContract.apiVersion, label: "API", systemImage: "point.3.connected.trianglepath.dotted")
            MetricTile(value: "\(SuperBrainContract.capabilities.count)", label: "Capabilities", systemImage: "square.grid.3x3.fill")
        }
    }

    private var realityForkCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(SuperBrainTheme.accent)
                        .frame(width: 54, height: 54)
                    Image(systemName: "point.3.filled.connected.trianglepath.dotted")
                        .font(.title2.bold())
                        .foregroundStyle(.white)
                }

                VStack(alignment: .leading, spacing: 5) {
                    Text("NEXUS Reality Fork")
                        .font(.headline)
                        .foregroundStyle(.white)
                    Text("Vertak een beslissing in toetsbare toekomstpaden, aannames en reality-signals.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            HStack(spacing: 8) {
                StatusChip(title: "Prediction Contract", systemImage: "lock.shield", active: true)
                StatusChip(title: "Fail-closed scoring", systemImage: "checkmark.seal", active: true)
            }

            Button {
                showRealityFork = true
            } label: {
                HStack {
                    Label("Fork een beslissing", systemImage: "arrow.triangle.branch")
                        .fontWeight(.bold)
                    Spacer()
                    Image(systemName: "arrow.up.right")
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(.white.opacity(0.18))
        }
        .superBrainGlassCard()
    }

    private var voiceCard: some View {
        VStack(spacing: 16) {
            CockpitSectionHeader("Voice Control", subtitle: "Praat rechtstreeks met de cockpit")

            Button {
                if voice.isListening {
                    voice.stop(clearTranscript: false)
                } else {
                    Task { await voice.start() }
                }
            } label: {
                ZStack {
                    Circle()
                        .fill(SuperBrainTheme.accent)
                        .frame(width: 86, height: 86)
                        .shadow(color: .blue.opacity(voice.isListening ? 0.45 : 0.16), radius: voice.isListening ? 28 : 12)
                    Circle()
                        .stroke(.white.opacity(voice.isListening ? 0.55 : 0.16), lineWidth: 1)
                        .frame(width: voice.isListening ? 104 : 96, height: voice.isListening ? 104 : 96)
                    Image(systemName: voice.isListening ? "waveform" : "mic.fill")
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(.white)
                }
                .animation(.easeInOut(duration: 0.25), value: voice.isListening)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(voice.isListening ? "Stop luisteren" : "Start voice control")

            Text(voice.isListening ? "Luistert…" : "Tik en spreek een opdracht uit")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(voice.isListening ? .white : .secondary)

            if !voice.transcript.isEmpty {
                Text("“\(voice.transcript)”")
                    .font(.body)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                Button {
                    handleVoice(voice.transcript)
                } label: {
                    Label("Gebruik spraakopdracht", systemImage: "arrow.up.circle.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
            }

            Text("Voorbeelden: “vernieuw status”, “onderzoek quantum computing”, “fork deze beslissing”, of spreek gewoon je vraag in.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .superBrainGlassCard()
    }

    private var missionComposer: some View {
        VStack(alignment: .leading, spacing: 14) {
            CockpitSectionHeader("Nieuwe missie", subtitle: "Van snelle vraag tot brononderzoek")

            TextField("Wat wil je SuperBrain laten onderzoeken?", text: $question, axis: .vertical)
                .lineLimit(3...7)
                .padding(14)
                .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .accessibilityIdentifier("missionQuestion")

            Picker("Werkwijze", selection: $research) {
                Text("Quick").tag(false)
                Text("Deep Research").tag(true)
            }
            .pickerStyle(.segmented)

            Button {
                startMission()
            } label: {
                HStack {
                    if store.busy {
                        ProgressView()
                    } else {
                        Image(systemName: research ? "atom" : "sparkles")
                    }
                    Text(store.busy ? "NEXUS denkt…" : "Start missie")
                        .fontWeight(.bold)
                    Spacer()
                    Image(systemName: "arrow.up.right")
                }
                .padding(.vertical, 4)
            }
            .buttonStyle(.borderedProminent)
            .tint(.white.opacity(0.18))
            .disabled(!canStartMission)
        }
        .superBrainGlassCard()
    }

    private func latestResponseCard(_ response: MissionResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            CockpitSectionHeader("Laatste NEXUS-output", subtitle: response.verificationNote)
            HStack {
                Text(response.nexusFinalValue)
                    .font(.title2.bold())
                    .foregroundStyle(.white)
                Spacer()
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(.green)
            }

            ForEach(Array((response.draftResponses ?? []).enumerated()), id: \.offset) { _, draft in
                VStack(alignment: .leading, spacing: 5) {
                    Text(draft.agent ?? "Model")
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                    Text(draft.text ?? "Geen antwoordtekst")
                        .foregroundStyle(.white)
                        .textSelection(.enabled)
                }
                .padding(.top, 5)
            }
        }
        .superBrainGlassCard()
    }

    private var missionsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            CockpitSectionHeader("Recente missies", subtitle: "Besluiten, bewijs en audit trail")

            if store.missions.isEmpty {
                Text("Nog geen missies")
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 6)
            } else {
                ForEach(store.missions.prefix(8)) { mission in
                    NavigationLink(value: mission.runId) {
                        HStack(spacing: 12) {
                            ZStack {
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(.white.opacity(0.06))
                                    .frame(width: 42, height: 42)
                                Image(systemName: "scope")
                                    .foregroundStyle(.secondary)
                            }
                            VStack(alignment: .leading, spacing: 4) {
                                Text(mission.question)
                                    .foregroundStyle(.white)
                                    .lineLimit(2)
                                Text("\(mission.finalValue ?? "—") · \(mission.status)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption.bold())
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .superBrainGlassCard()
    }

    private var canStartMission: Bool {
        let clean = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, !store.busy else { return false }
        if research { return store.status?.researchMissionsAvailable != false }
        return store.status?.interactiveMissionsAvailable != false
    }

    private func startMission() {
        let mission = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !mission.isEmpty else { return }
        Task {
            await store.start(mission, research: research)
            if store.error == nil { question = "" }
        }
    }

    private func handleVoice(_ spoken: String) {
        guard let command = voice.command(from: spoken) else { return }
        switch command {
        case .refresh:
            Task { await store.refresh() }
        case .openSettings:
            showSettings = true
        case .mission(let text, let shouldResearch):
            question = text
            research = shouldResearch
            startMission()
        case .realityFork(let text):
            if !text.isEmpty { question = text }
            showRealityFork = true
        case .draft(let text):
            question = text
        }
        voice.stop(clearTranscript: true)
    }

    private func consumeShortcutMission() {
        let defaults = UserDefaults.standard
        guard let mission = defaults.string(forKey: "pendingShortcutMission"), !mission.isEmpty else { return }
        question = mission
        research = defaults.bool(forKey: "pendingShortcutResearch")
        defaults.removeObject(forKey: "pendingShortcutMission")
        defaults.removeObject(forKey: "pendingShortcutResearch")
    }
}
