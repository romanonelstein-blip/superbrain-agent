import SwiftUI

@MainActor
final class MissionStore: ObservableObject {
    @Published var address = UserDefaults.standard.string(forKey: "serverAddress") ?? ""
    @Published var status: RuntimeStatus?
    @Published var missions: [Mission] = []
    @Published var busy = false
    @Published var error: String?
    @Published var latestResponse: MissionResponse?

    var api: MissionAPI { MissionAPI(address: address, token: AccessToken.read()) }

    func configure(address: String, token: String) throws {
        try MissionAPI.validate(address)
        try AccessToken.save(token.trimmingCharacters(in: .whitespacesAndNewlines))
        self.address = address.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(self.address, forKey: "serverAddress")
        status = nil
        missions = []
        latestResponse = nil
    }

    func refresh() async {
        guard !address.isEmpty else { return }
        do {
            async let runtime = api.status()
            async let entries = api.missions()
            let (newStatus, newMissions) = try await (runtime, entries)
            status = newStatus
            missions = newMissions
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    func start(_ question: String, research: Bool) async {
        busy = true
        defer { busy = false }
        do {
            let result = try await api.start(question, research: research)
            latestResponse = result
            error = nil
            await refresh()
        } catch { self.error = error.localizedDescription }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: MissionStore
    @State private var showSettings = false
    @State private var question = ""
    @State private var research = false

    var body: some View {
        NavigationStack {
            List {
                if store.address.isEmpty {
                    ContentUnavailableView("Verbind SuperBrain", systemImage: "network",
                                           description: Text("Stel het beveiligde serveradres en je toegangstoken in."))
                } else {
                    Section("NEXUS-1000") {
                        Label(store.status == nil ? "Niet verbonden" : "Verbonden", systemImage: store.status == nil ? "wifi.slash" : "checkmark.shield")
                        if let status = store.status {
                            Text("Beslismotor: \(status.canonicalRuntime)")
                            Text("Model: \(status.configuredProviders.joined(separator: ", ").isEmpty ? "niet ingesteld" : status.configuredProviders.joined(separator: ", "))")
                                .foregroundStyle(.secondary)
                        }
                    }
                    Section("Nieuwe opdracht") {
                        TextField("Wat wil je SuperBrain laten onderzoeken?", text: $question, axis: .vertical)
                            .lineLimit(3...7)
                            .accessibilityIdentifier("missionQuestion")
                        Picker("Werkwijze", selection: $research) {
                            Text("Snel antwoord").tag(false)
                            Text("Onderzoek met bronnen").tag(true)
                        }
                        Button {
                            let mission = question.trimmingCharacters(in: .whitespacesAndNewlines)
                            Task {
                                await store.start(mission, research: research)
                                if store.error == nil { question = "" }
                            }
                        } label: {
                            if store.busy { ProgressView() } else { Label("Start opdracht", systemImage: "sparkles") }
                        }
                        .disabled(question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.busy || (research ? store.status?.researchMissionsAvailable == false : store.status?.interactiveMissionsAvailable == false))
                    }
                    if let response = store.latestResponse {
                        Section("Laatste antwoord") {
                            let drafts = response.draftResponses ?? []
                            Text("NEXUS: \(response.nexusFinalValue)").font(.headline)
                            if let note = response.verificationNote { Text(note).foregroundStyle(.secondary) }
                            ForEach(drafts.indices, id: \.self) { index in
                                let draft = drafts[index]
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(draft.agent ?? "Modelantwoord").font(.subheadline.bold())
                                    Text(draft.text ?? "Geen antwoordtekst").textSelection(.enabled)
                                    if draft.verified != true { Label("Niet onafhankelijk geverifieerd", systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange) }
                                }
                            }
                        }
                    }
                    Section("Opdrachten") {
                        if store.missions.isEmpty { Text("Nog geen opdrachten").foregroundStyle(.secondary) }
                        ForEach(store.missions) { mission in
                            NavigationLink(value: mission.runId) {
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(mission.question).lineLimit(2)
                                    Text("\(mission.finalValue ?? "—") · \(mission.status)").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("SuperBrain")
            .navigationDestination(for: String.self) { MissionDetailView(id: $0) }
            .toolbar {
                Button { showSettings = true } label: {
                    Image(systemName: "gearshape").accessibilityLabel("Instellingen")
                }
            }
            .refreshable { await store.refresh() }
            .task { if !store.address.isEmpty { await store.refresh() } else { showSettings = true } }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .alert("SuperBrain", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) {
                Button("OK") { store.error = nil }
            } message: { Text(store.error ?? "") }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject private var store: MissionStore
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var token = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Verbinding") {
                    TextField("https://jouw-superbrain.example", text: $address)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .keyboardType(.URL)
                    SecureField("Toegangstoken", text: $token)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("De iPhone-app gebruikt de Mission Control API. Het token wordt alleen op dit toestel in de sleutelhanger opgeslagen.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Instellingen")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Sluiten") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Bewaar") {
                        do {
                            try store.configure(address: address, token: token)
                            dismiss()
                            Task { await store.refresh() }
                        } catch { self.error = error.localizedDescription }
                    }
                }
            }
            .onAppear { address = store.address; token = AccessToken.read() }
        }
    }
}

struct MissionDetailView: View {
    @EnvironmentObject private var store: MissionStore
    let id: String
    @State private var detail: MissionDetail?
    @State private var action = "RESEARCH_MORE"
    @State private var note = ""
    @State private var pendingConfirmation = false
    @State private var saving = false
    @State private var error: String?
    private let actions = ["ACCEPT", "MODIFY", "RESEARCH_MORE", "OVERRIDE", "REJECT"]

    var body: some View {
        List {
            if let detail {
                Section("Besluit van NEXUS") {
                    Text(detail.run.question).font(.headline)
                    LabeledContent("Uitkomst", value: detail.run.finalValue ?? "—")
                    LabeledContent("Status", value: detail.run.status)
                    Text("Run: \(id)").font(.caption).textSelection(.enabled)
                }
                Section("Bewijs · \(detail.evidence.count)") {
                    if detail.evidence.isEmpty { Text("Geen bewijs vastgelegd").foregroundStyle(.secondary) }
                    ForEach(detail.evidence) { evidence in
                        VStack(alignment: .leading, spacing: 4) {
                            Label(evidence.verified ? "Geverifieerd" : "Niet geverifieerd", systemImage: evidence.verified ? "checkmark.seal" : "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(evidence.verified ? Color.green : Color.orange)
                            Text(evidence.claim).textSelection(.enabled)
                            Text(evidence.sourceFamily ?? evidence.sourceId ?? "Bron onbekend").font(.caption).foregroundStyle(.secondary)
                            if let citation = evidence.citation { Text(citation).font(.caption).textSelection(.enabled) }
                        }
                    }
                }
                Section("Controlepad") {
                    ForEach(detail.audit.indices, id: \.self) { index in
                        let event = detail.audit[index]
                        VStack(alignment: .leading) { Text(event.stage).font(.subheadline.bold()); Text(event.detail).font(.caption).textSelection(.enabled) }
                    }
                }
                Section("Mijn beslissing") {
                    Picker("Actie", selection: $action) { ForEach(actions, id: \.self) { Text($0).tag($0) } }
                    TextField("Toelichting (optioneel)", text: $note, axis: .vertical).lineLimit(2...5)
                    Button("Leg beslissing vast") { pendingConfirmation = true }.disabled(saving)
                    ForEach(detail.masterDecisions.indices, id: \.self) { index in
                        let decision = detail.masterDecisions[index]
                        VStack(alignment: .leading) {
                            Text(decision.action).font(.subheadline.bold())
                            Text(decision.note.isEmpty ? "Geen toelichting" : decision.note)
                            Text(decision.createdAt).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Text("Dit registreert jouw besluit. Het verandert de uitkomst van NEXUS niet en voert geen externe actie uit.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else if let error { ContentUnavailableView(error, systemImage: "exclamationmark.triangle") }
            else { ProgressView("Opdracht laden…") }
        }
        .navigationTitle("Opdracht")
        .confirmationDialog("Beslissing \(action) vastleggen?", isPresented: $pendingConfirmation) {
            Button("Bevestig") {
                saving = true
                Task {
                    do { _ = try await store.api.decide(id, action: action, note: note); note = ""; await load() }
                    catch { self.error = error.localizedDescription }
                    saving = false
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .alert("SuperBrain", isPresented: Binding(get: { error != nil && detail != nil }, set: { if !$0 { error = nil } })) {
            Button("OK") { error = nil }
        } message: { Text(error ?? "") }
    }

    private func load() async {
        do { detail = try await store.api.detail(id); error = nil }
        catch { error = error.localizedDescription }
    }
}
