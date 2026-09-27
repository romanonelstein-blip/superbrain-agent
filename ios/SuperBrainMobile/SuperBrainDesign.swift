import SwiftUI

enum SuperBrainTheme {
    static let pagePadding: CGFloat = 20
    static let cardRadius: CGFloat = 24

    static var background: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.025, green: 0.035, blue: 0.075),
                Color(red: 0.055, green: 0.035, blue: 0.12),
                Color(red: 0.02, green: 0.08, blue: 0.105)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    static var accent: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 0.42, green: 0.72, blue: 1.0),
                Color(red: 0.67, green: 0.43, blue: 1.0),
                Color(red: 0.26, green: 0.94, blue: 0.82)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}

struct SuperBrainBackground: View {
    var body: some View {
        ZStack {
            SuperBrainTheme.background
                .ignoresSafeArea()

            Circle()
                .fill(Color.blue.opacity(0.18))
                .frame(width: 320, height: 320)
                .blur(radius: 70)
                .offset(x: -160, y: -300)

            Circle()
                .fill(Color.purple.opacity(0.16))
                .frame(width: 360, height: 360)
                .blur(radius: 90)
                .offset(x: 170, y: -80)

            Circle()
                .fill(Color.mint.opacity(0.10))
                .frame(width: 300, height: 300)
                .blur(radius: 90)
                .offset(x: 120, y: 380)
        }
    }
}

struct GlassCardModifier: ViewModifier {
    var padding: CGFloat = 18

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: SuperBrainTheme.cardRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: SuperBrainTheme.cardRadius, style: .continuous)
                    .stroke(.white.opacity(0.10), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.24), radius: 22, y: 12)
    }
}

extension View {
    func superBrainGlassCard(padding: CGFloat = 18) -> some View {
        modifier(GlassCardModifier(padding: padding))
    }
}

struct StatusChip: View {
    let title: String
    let systemImage: String
    let active: Bool

    var body: some View {
        Label(title, systemImage: systemImage)
            .font(.caption.weight(.semibold))
            .foregroundStyle(active ? .white : .secondary)
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .background(
                Capsule()
                    .fill(active ? Color.green.opacity(0.18) : Color.white.opacity(0.06))
            )
            .overlay {
                Capsule().stroke(.white.opacity(0.08), lineWidth: 1)
            }
    }
}

struct MetricTile: View {
    let value: String
    let label: String
    let systemImage: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: systemImage)
                .font(.headline)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .superBrainGlassCard(padding: 14)
    }
}

struct CockpitSectionHeader: View {
    let title: String
    let subtitle: String?

    init(_ title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.headline)
                .foregroundStyle(.white)
            if let subtitle {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
