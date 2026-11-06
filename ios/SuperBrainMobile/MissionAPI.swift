import Foundation
import Security

struct RuntimeStatus: Decodable {
    let canonicalRuntime: String
    let interactiveMissionsAvailable: Bool
    let researchMissionsAvailable: Bool
    let configuredProviders: [String]
    let superBrainVersion: String?
    let apiVersion: String?
    let capabilities: [String]?

    var missingRequiredMobileCapabilities: [String] {
        guard let capabilities else { return [] }
        return Array(SuperBrainContract.requiredCapabilityIDs.subtracting(Set(capabilities))).sorted()
    }
}

struct Mission: Identifiable, Decodable {
    let runId: String
    let question: String
    let status: String
    let finalValue: String?
    let createdAt: String?
    var id: String { runId }
}

struct EvidenceItem: Identifiable, Decodable {
    let id: String
    let claim: String
    let verified: Bool
    let sourceId: String?
    let sourceFamily: String?
    let trustBoundary: String?
    let citation: String?
    let stance: String?
}

struct AuditItem: Decodable {
    let stage: String
    let detail: String
}

struct MasterDecision: Decodable {
    let action: String
    let note: String
    let createdAt: String
}

struct MissionDetail: Decodable {
    let run: Mission
    let evidence: [EvidenceItem]
    let audit: [AuditItem]
    let masterDecisions: [MasterDecision]
}

struct MissionResponse: Decodable {
    struct Draft: Decodable {
        let agent: String?
        let text: String?
        let verified: Bool?
    }
    let runId: String
    let nexusFinalValue: String
    let verificationNote: String?
    let draftResponses: [Draft]?
}

private struct MissionList: Decodable { let missions: [Mission] }
private struct ServerError: Decodable { let error: String; let detail: String? }

enum MissionAPIError: LocalizedError {
    case invalidAddress, insecureAddress, noConnection, unauthorized, server(String)

    var errorDescription: String? {
        switch self {
        case .invalidAddress: return "Vul een geldig serveradres in."
        case .insecureAddress: return "Gebruik HTTPS voor een verbinding met SuperBrain."
        case .noConnection: return "Geen verbinding met SuperBrain. Controleer het adres en de server."
        case .unauthorized: return "Toegang geweigerd. Controleer je toegangstoken."
        case .server(let message): return message
        }
    }
}

enum AccessToken {
    private static let service = "SuperBrainMobile.MissionControl"
    private static let account = "bearer"

    static func read() -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account,
                                    kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else { return "" }
        return token
    }

    static func save(_ token: String) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        if token.isEmpty { return }
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else {
            throw MissionAPIError.server("Toegangstoken kon niet veilig worden opgeslagen.")
        }
    }
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

struct MissionAPI {
    let address: String
    let token: String

    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 240
        return URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
    }()

    private var baseURL: URL? {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parts = URLComponents(string: trimmed), let scheme = parts.scheme?.lowercased(),
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.path.isEmpty || parts.path == "/", parts.query == nil, parts.fragment == nil,
              let url = parts.url else { return nil }
        guard scheme == "https" || Self.simulatorLoopback(scheme: scheme, host: host) else { return nil }
        return url
    }

    static func validate(_ address: String) throws {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parts = URLComponents(string: trimmed), let scheme = parts.scheme?.lowercased() else {
            throw MissionAPIError.invalidAddress
        }
        guard scheme == "https" || simulatorLoopback(scheme: scheme, host: parts.host ?? "") else {
            throw MissionAPIError.insecureAddress
        }
        guard MissionAPI(address: trimmed, token: "").baseURL != nil else { throw MissionAPIError.invalidAddress }
    }

    private static func simulatorLoopback(scheme: String, host: String) -> Bool {
        #if targetEnvironment(simulator)
        return scheme == "http" && (host == "127.0.0.1" || host == "localhost" || host == "::1")
        #else
        return false
        #endif
    }

    private func request<T: Decodable>(_ path: String, body: [String: String]? = nil) async throws -> T {
        try Self.validate(address)
        guard let baseURL, let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
            throw MissionAPIError.invalidAddress
        }
        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let result: (Data, URLResponse)
        do { result = try await Self.session.data(for: request) }
        catch { throw MissionAPIError.noConnection }
        let (data, response) = result
        guard let http = response as? HTTPURLResponse else { throw MissionAPIError.noConnection }
        if http.statusCode == 401 { throw MissionAPIError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            let detail = try? JSONDecoder().decode(ServerError.self, from: data)
            throw MissionAPIError.server(detail?.detail ?? detail?.error ?? "Serverfout (\(http.statusCode)).")
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    func status() async throws -> RuntimeStatus { try await request("/api/system/status") }
    func missions() async throws -> [Mission] {
        let result: MissionList = try await request("/api/missions")
        return result.missions
    }
    func detail(_ id: String) async throws -> MissionDetail {
        guard let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              !encoded.contains("/") else { throw MissionAPIError.invalidAddress }
        return try await request("/api/missions/\(encoded)")
    }
    func start(_ mission: String, research: Bool) async throws -> MissionResponse {
        try await request(research ? "/api/missions/research" : "/api/missions/ask", body: ["mission": mission])
    }
    func decide(_ id: String, action: String, note: String) async throws -> MasterDecision {
        guard let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              !encoded.contains("/") else { throw MissionAPIError.invalidAddress }
        return try await request("/api/missions/\(encoded)/master-decision", body: ["action": action, "note": note])
    }
}
