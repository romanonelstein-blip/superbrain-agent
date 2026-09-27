import CryptoKit
import SwiftUI

struct RealityForkPath: Identifiable, Hashable {
    let id: UUID
    let key: String
    let title: String
    let thesis: String
    let assumptions: [String]
    let signalsToWatch: [String]
    let counterSignal: String

    init(key: String, title: String, thesis: String, assumptions: [String], signalsToWatch: [String], counterSignal: String) {
        self.id = UUID()
        self.key = key
        self.title = title
        self.thesis = thesis
        self.assumptions = assumptions
        self.signalsToWatch = signalsToWatch
        self.counterSignal = counterSignal
    }
}

struct RealityForkDraft: Identifiable, Hashable {
    let id: UUID
    let decision: String
    let createdAt: Date
    let paths: [RealityForkPath]
    let integrityHash: String

    init(decision: String, createdAt: Date, paths: [RealityForkPath]) {
        self.id = UUID()
        self.decision = decision
        self.createdAt = createdAt
        self.paths = paths

        let payload = ([decision, ISO8601DateFormatter().string(from: createdAt)] + paths.flatMap { path in
            [path.key, path.title, path.thesis] + path.assumptions + path.signalsToWatch + [path.counterSignal]
        }).joined(separator: "\u{001F}")
        self.integrityHash = SHA256.hash(data: Data(payload.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

struct RealityForkNexusPath: Identifiable, Hashable {
    let id: String
    let key: String
    let title: String
    let runId: String
    let verdict: String
    let verificationNote: String?
    let evidenceClaims: [String]
    let sourceFamilies: [String]

    var isSupported: Bool { verdict == "SUPPORTED" }
}

struct RealityForkNexusAnalysis: Identifiable, Hashable {
    let id: UUID
    let decision: String
    let createdAt: Date
    let paths: [RealityForkNexusPath]
    let integrityHash: String

    init(decision: String, createdAt: Date, paths: [RealityForkNexusPath]) {
        self.id = UUID()
        self.decision = decision
        self.createdAt = createdAt
        self.paths = paths
        let payload = ([decision, ISO8601DateFormatter().string(from: createdAt)] + paths.flatMap { path in
            [path.key, path.title, path.runId, path.verdict, path.verificationNote ?? ""] + path.evidenceClaims + path.sourceFamilies
        }).joined(separator: "\u{001F}")
        self.integrityHash = SHA256.hash(data: Data(payload.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

enum RealityForkPlanner {
    static func draft(for rawDecision: String) -> RealityForkDraft? {
        let decision = rawDecision.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !decision.isEmpty else { return nil }
        return RealityForkDraft(decision: decision, createdAt: Date(), paths: canonicalPaths)
    }

    static func analyzeWithNexus(decision rawDecision: String, api: MissionAPI) async throws -> RealityForkNexusAnalysis {
        let decision = rawDecision.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !decision.isEmpty else { throw MissionAPIError.server("Voer eerst een beslissing in.") }

        var results: [RealityForkNexusPath] = []
        for path in canonicalPaths {
            let mission = nexusMission(decision: decision, path: path)
            let response = try await api.start(mission, research: true)
            let detail = try await api.detail(response.runId)
            let verifiedEvidence = detail.evidence.filter(\.verified)
            guard !verifiedEvidence.isEmpty else {
                throw MissionAPIError.server("NEXUS leverde geen geverifieerd bewijs voor het pad ‘\(path.title)’. Reality Fork blijft fail-closed.")
            }

            let claims = Array(verifiedEvidence.prefix(4).map(\.claim))
            let families = Array(Set(verifiedEvidence.compactMap(\.sourceFamily))).sorted()
            results.append(
                RealityForkNexusPath(
                    id: path.key,
                    key: path.key,
                    title: path.title,
                    runId: response.runId,
                    verdict: response.nexusFinalValue.uppercased() == "YES" ? "SUPPORTED" : "NOT_SUPPORTED",
                    verificationNote: response.verificationNote,
                    evidenceClaims: claims,
                    sourceFamilies: families
                )
            )
        }

        return RealityForkNexusAnalysis(decision: decision, createdAt: Date(), paths: results)
    }

    private static var canonicalPaths: [RealityForkPath] {
        [
            RealityForkPath(
                key: "ACT_NOW",
                title: "Act now",
                thesis: "Voer de beslissing nu uit en meet direct of de belangrijkste aannames standhouden.",
                assumptions: [
                    "De huidige informatie is voldoende om verantwoord te handelen.",
                    "De kosten van wachten zijn waarschijnlijk hoger dan de kosten van een gecontroleerde eerste stap."
                ],
                signalsToWatch: [
                    "Vroege bevestiging van het gewenste effect",
                    "Nieuwe risico’s of onverwachte neveneffecten"
                ],
                counterSignal: "Stop of herbereken zodra een kernvoorwaarde aantoonbaar wegvalt."
            ),
            RealityForkPath(
                key: "WAIT_OBSERVE",
                title: "Wait & observe",
                thesis: "Stel de beslissing tijdelijk uit en verzamel alleen informatie die de keuze werkelijk kan veranderen.",
                assumptions: [
                    "Er kan binnen een redelijke termijn betekenisvol nieuw bewijs verschijnen.",
                    "Uitstel veroorzaakt geen onomkeerbare schade of gemiste kans."
                ],
                signalsToWatch: [
                    "Nieuwe evidence met hoge informatiewaarde",
                    "Verandering in urgentie, kosten of timing"
                ],
                counterSignal: "Acteer zodra wachten minder informatie oplevert dan het kost."
            ),
            RealityForkPath(
                key: "CONTRARIAN",
                title: "Contrarian route",
                thesis: "Test bewust een derde route om te voorkomen dat de keuze ten onrechte als alleen A of B wordt gezien.",
                assumptions: [
                    "De huidige framing kan een bruikbaar alternatief verbergen.",
                    "Een kleinere of omkeerbare proef kan meer leren dan een volledige keuze."
                ],
                signalsToWatch: [
                    "Alternatieven met betere reversibility",
                    "Bewijs dat de oorspronkelijke probleemdefinitie onvolledig is"
                ],
                counterSignal: "Laat de alternatieve route vallen wanneer hij geen extra informatiewaarde of risicoreductie biedt."
            )
        ]
    }

    private static func nexusMission(decision: String, path: RealityForkPath) -> String {
        """
        NEXUS REALITY FORK scenario-evaluatie.
        Dit is uitsluitend decision intelligence: voer geen externe actie uit.

        Oorspronkelijke beslissing:
        \(decision)

        Te beoordelen pad: \(path.key) — \(path.title)
        Hypothese: \(path.thesis)
        Aannames: \(path.assumptions.joined(separator: " | "))
        Signalen om te volgen: \(path.signalsToWatch.joined(separator: " | "))
        Counter-signal: \(path.counterSignal)

        Beoordeel of dit specifieke pad door de huidige geverifieerde evidence wordt ondersteund. Gebruik onafhankelijke dissent en de bestaande NEXUS/NEIS-gates. Geef alleen een goedgekeurd YES wanneer de evidence-gates slagen; anders NO. Geen kanspercentages verzinnen.
        """
    }
}

struct RealityForkSheet: View {
    @EnvironmentObject private var store: MissionStore
    @Environment(\.dismiss) private var dismiss
    @State private var decision: String
    @State private var draft: RealityForkDraft?
    @State private var analysis: RealityForkNexusAnalysis?
    @State private var analyzing = false
    @State private var analysisError: String?

    init(seed: String) {
        _decision = State(initialValue: seed)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                SuperBrainBackground()

                ScrollView {
                    VStack(spacing: 18) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("NEXUS REALITY FORK")
                                .font(.caption.weight(.heavy))
                                .tracking(1.8)
                                .foregroundStyle(.secondary)
                            Text("Vertak één beslissing in meerdere toetsbare routes.")
                                .font(.title2.bold())
                                .foregroundStyle(.white)
                            Text("NEXUS beoordeelt elk pad apart met geverifieerde research-evidence. Er worden bewust geen kanspercentages verzonnen.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .superBrainGlassCard()

                        VStack(alignment: .leading, spacing: 12) {
                            TextField("Welke beslissing wil je vertakken?", text: $decision, axis: .vertical)
                                .lineLimit(3...7)
                                .padding(14)
                                .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                            Button {
                                runNexusFork()
                            } label: {
                                HStack {
                                    if analyzing { ProgressView().tint(.white) }
                                    Label(analyzing ? "NEXUS analyseert…" : "Fork met NEXUS", systemImage: "point.3.filled.connected.trianglepath.dotted")
                                    Spacer()
                                }
                                .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(decision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || analyzing || store.status?.researchMissionsAvailable != true)

                            if store.status?.researchMissionsAvailable != true {
                                Label("Research is nog gated. Reality Fork voert geen gescoorde analyse uit zonder NEXUS + evidence provider.", systemImage: "lock.shield")
                                    .font(.caption)
                                    .foregroundStyle(.orange)
                            }
                        }
                        .superBrainGlassCard()

                        if let analysisError {
                            Label(analysisError, systemImage: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(.orange)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .superBrainGlassCard()
                        }

                        if let analysis {
                            nexusContract(analysis)
                            ForEach(Array(analysis.paths.enumerated()), id: \.element.id) { index, path in
                                nexusPathCard(path, index: index)
                            }
                        } else if let draft {
                            predictionContract(draft)
                            ForEach(Array(draft.paths.enumerated()), id: \.element.id) { index, path in
                                pathCard(path, index: index)
                            }
                        }
                    }
                    .padding(.horizontal, SuperBrainTheme.pagePadding)
                    .padding(.vertical, 18)
                }
            }
            .navigationTitle("Reality Fork")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Sluiten") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private func runNexusFork() {
        guard let newDraft = RealityForkPlanner.draft(for: decision) else { return }
        draft = newDraft
        analysis = nil
        analysisError = nil
        analyzing = true
        Task {
            do {
                analysis = try await RealityForkPlanner.analyzeWithNexus(decision: newDraft.decision, api: store.api)
                analysisError = nil
            } catch {
                analysisError = error.localizedDescription
            }
            analyzing = false
        }
    }

    private func nexusContract(_ analysis: RealityForkNexusAnalysis) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            CockpitSectionHeader("Prediction Contract", subtitle: "NEXUS-backed scenario-evaluatie")
            Text(analysis.decision)
                .font(.headline)
                .foregroundStyle(.white)
            Label("NEXUS VERIFIED · \(analysis.paths.count) paden", systemImage: "checkmark.shield.fill")
                .font(.caption.weight(.bold))
                .foregroundStyle(.green)
            Text("Result fingerprint  \(analysis.integrityHash.prefix(16))…")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Text("De fingerprint wordt op de iPhone berekend over de server-run-ID’s, NEXUS-uitkomsten en teruggeleverde evidence. De bronruns blijven afzonderlijk auditbaar in Mission Control.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .superBrainGlassCard()
    }

    private func predictionContract(_ draft: RealityForkDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            CockpitSectionHeader("Prediction Contract", subtitle: "Lokale structuur terwijl NEXUS analyseert")
            Text(draft.decision)
                .font(.headline)
                .foregroundStyle(.white)
            Label("UNSCORED · evidence nodig", systemImage: "lock.shield")
                .font(.caption.weight(.bold))
                .foregroundStyle(.orange)
            Text("SHA-256  \(draft.integrityHash.prefix(16))…")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .superBrainGlassCard()
    }

    private func nexusPathCard(_ path: RealityForkNexusPath, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                ZStack {
                    Circle()
                        .fill(SuperBrainTheme.accent)
                        .frame(width: 38, height: 38)
                    Text("\(index + 1)")
                        .font(.subheadline.bold())
                        .foregroundStyle(.white)
                }
                Text(path.title)
                    .font(.headline)
                    .foregroundStyle(.white)
                Spacer()
                Text(path.verdict)
                    .font(.caption2.weight(.heavy))
                    .foregroundStyle(path.isSupported ? .green : .orange)
            }

            if let note = path.verificationNote, !note.isEmpty {
                Text(note)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 7) {
                Text("Verified evidence")
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                ForEach(path.evidenceClaims, id: \.self) { claim in
                    Label(claim, systemImage: "checkmark.seal")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            HStack {
                Label("\(path.evidenceClaims.count) claims", systemImage: "doc.text.magnifyingglass")
                Spacer()
                Text("run \(path.runId.prefix(8))…")
                    .monospaced()
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

            if !path.sourceFamilies.isEmpty {
                Text("Bronfamilies: \(path.sourceFamilies.joined(separator: ", "))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .superBrainGlassCard()
    }

    private func pathCard(_ path: RealityForkPath, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                ZStack {
                    Circle()
                        .fill(SuperBrainTheme.accent)
                        .frame(width: 38, height: 38)
                    Text("\(index + 1)")
                        .font(.subheadline.bold())
                        .foregroundStyle(.white)
                }
                Text(path.title)
                    .font(.headline)
                    .foregroundStyle(.white)
                Spacer()
                Text("UNSCORED")
                    .font(.caption2.weight(.heavy))
                    .foregroundStyle(.orange)
            }

            Text(path.thesis)
                .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 6) {
                Text("Aannames")
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                ForEach(path.assumptions, id: \.self) { assumption in
                    Label(assumption, systemImage: "circle.dashed")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Reality signals")
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                ForEach(path.signalsToWatch, id: \.self) { signal in
                    Label(signal, systemImage: "waveform.path.ecg")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Label(path.counterSignal, systemImage: "exclamationmark.arrow.triangle.2.circlepath")
                .font(.caption)
                .foregroundStyle(.orange)
        }
        .superBrainGlassCard()
    }
}
