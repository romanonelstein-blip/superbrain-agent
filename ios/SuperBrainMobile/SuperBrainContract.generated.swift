// GENERATED FILE. DO NOT EDIT.
// Source: shared/superbrain-mobile-contract.json + package.json
import Foundation

struct BundledCapability: Identifiable, Hashable {
    let id: String
    let title: String
    let kind: String
    let method: String?
    let endpoint: String?
    let mobileSupport: String
    let required: Bool
}

enum SuperBrainContract {
    static let schemaVersion = 1
    static let coreVersion = "0.1.0"
    static let apiVersion = "1"
    static let iosClientVersion = "0.2.0"

    static let capabilities: [BundledCapability] = [
        BundledCapability(
            id: "runtime_status",
            title: "Runtime-status",
            kind: "endpoint",
            method: "GET",
            endpoint: "/api/system/status",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "mission_list",
            title: "Opdrachtgeschiedenis",
            kind: "endpoint",
            method: "GET",
            endpoint: "/api/missions",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "mission_ask",
            title: "Snelle opdracht",
            kind: "endpoint",
            method: "POST",
            endpoint: "/api/missions/ask",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "mission_research",
            title: "Onderzoek met bronnen",
            kind: "endpoint",
            method: "POST",
            endpoint: "/api/missions/research",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "mission_detail",
            title: "Opdrachtdetail",
            kind: "endpoint",
            method: "GET",
            endpoint: "/api/missions/{runId}",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "master_decision",
            title: "Master-beslissing",
            kind: "endpoint",
            method: "POST",
            endpoint: "/api/missions/{runId}/master-decision",
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "evidence_review",
            title: "Bewijs en broncontrole",
            kind: "model",
            method: nil,
            endpoint: nil,
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "audit_trail",
            title: "Controlepad",
            kind: "model",
            method: nil,
            endpoint: nil,
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "local_device_lock",
            title: "Face ID / toestelcode",
            kind: "client",
            method: nil,
            endpoint: nil,
            mobileSupport: "native",
            required: true
        ),
        BundledCapability(
            id: "secure_token_storage",
            title: "Sleutelhanger-tokenopslag",
            kind: "client",
            method: nil,
            endpoint: nil,
            mobileSupport: "native",
            required: true
        )
    ]

    static let requiredCapabilityIDs = Set(capabilities.filter(\.required).map(\.id))
}
