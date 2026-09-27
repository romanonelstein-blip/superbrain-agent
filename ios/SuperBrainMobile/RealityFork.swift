import CryptoKit
import SwiftUI

struct RealityForkPath: Identifiable, Hashable {
    let id: UUID
    let title: String
    let thesis: String
    let assumptions: [String]
    let signalsToWatch: [String]
    let counterSignal: String

    init(title: String, thesis: String, assumptions: [String], signalsToWatch: [String], counterSignal: String) {
        self.id = UUID()
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
            [path.title, path.thesis] + path.assumptions + path.signalsToWatch + [path.counterSignal]
        }).joined(separator: "\u{001F}")
        self.integrityHash = SHA256.hash(data: Data(payload.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

enum RealityForkPlanner {
    static func draft(for rawDecision: String) -> RealityForkDraft? {
        let decision = rawDecision.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !decision.isEmpty else { return nil }

        let paths = [
            RealityForkPath(
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

        return RealityForkDraft(decision: decision, createdAt: Date(), paths: paths)
    }
}

struct RealityForkSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var decision: String
    @State private var draft: RealityForkDraft?

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
                            Text("Deze eerste iOS-versie maakt alleen een ongescoorde scenario-structuur. Kanspercentages blijven bewust uit totdat NEXUS ze met echte evidence kan onderbouwen.")
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
                                draft = RealityForkPlanner.draft(for: decision)
                            } label: {
                                Label("Fork deze beslissing", systemImage: "point.3.filled.connected.trianglepath.dotted")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(decision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                        .superBrainGlassCard()

                        if let draft {
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

    private func predictionContract(_ draft: RealityForkDraft) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            CockpitSectionHeader("Prediction Contract", subtitle: "Lokale integriteitsvingerafdruk, nog geen server-timestamp")
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
