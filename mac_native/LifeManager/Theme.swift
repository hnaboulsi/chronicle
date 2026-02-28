import AppKit
import SwiftUI

enum Spacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
}

// MARK: - Color Palette

extension Color {
    static let brand = Color.indigo
    static let greenTint = Color.green.opacity(0.08)
    static let orangeTint = Color.orange.opacity(0.08)
    static let redTint = Color.red.opacity(0.08)
    static let blueTint = Color.blue.opacity(0.08)
    static let purpleTint = Color.purple.opacity(0.08)
    static let indigoTint = Color.indigo.opacity(0.08)
    static let cardBackground = Color(NSColor.controlBackgroundColor)
}

// MARK: - StatusBadge

struct StatusBadge: View {
    let label: String
    let color: Color

    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, 3)
            .background(color.opacity(0.12), in: Capsule())
    }
}

// MARK: - StatusDot

struct StatusDot: View {
    let color: Color
    let label: String
    var isPulsing: Bool = false
    @State private var animatePulse = false

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
                .scaleEffect(isPulsing ? (animatePulse ? 1.2 : 0.9) : 1.0)
                .opacity(isPulsing && animatePulse ? 0.45 : 1.0)
                .animation(
                    isPulsing ? .easeInOut(duration: 1).repeatForever(autoreverses: true) : .default,
                    value: animatePulse
                )
            Text(label)
                .font(.subheadline)
        }
        .onAppear {
            animatePulse = isPulsing
        }
    }
}

// MARK: - InfoRow

struct InfoRow: View {
    let label: String
    let value: String
    var color: Color? = nil
    var mono: Bool = false

    var body: some View {
        HStack(alignment: .top) {
            Text(label)
                .foregroundStyle(.secondary)
                .font(.subheadline)
            Spacer(minLength: 16)
            Text(value)
                .font(mono ? .system(.caption, design: .monospaced) : .subheadline)
                .foregroundStyle(color ?? .primary)
                .multilineTextAlignment(.trailing)
                .lineLimit(3)
        }
    }
}

struct CopyableInfoRow: View {
    let label: String
    let value: String
    var color: Color? = nil
    var mono: Bool = false

    var body: some View {
        InfoRow(label: label, value: value, color: color, mono: mono)
            .contextMenu {
                Button("Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(value, forType: .string)
                }
            }
    }
}

// MARK: - DashboardCard

struct DashboardCard<Content: View>: View {
    let title: String
    let icon: String
    let iconColor: Color
    let tint: Color
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(iconColor)
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
            }
            content
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint, in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(tint.opacity(0.3), lineWidth: 1)
        )
        .shadow(color: tint.opacity(0.2), radius: 6, x: 0, y: 2)
    }
}

// MARK: - ChatBubble

struct ChatBubble: View {
    let text: String
    let isUser: Bool

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }
            Text(text)
                .font(.callout)
                .foregroundStyle(.primary)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    isUser ? Color.indigo.opacity(0.15) : Color(NSColor.controlBackgroundColor),
                    in: BubbleShape(isUser: isUser)
                )
                .overlay(
                    BubbleShape(isUser: isUser)
                        .strokeBorder(isUser ? Color.indigo.opacity(0.2) : Color.secondary.opacity(0.15), lineWidth: 1)
                )
            if !isUser { Spacer(minLength: 40) }
        }
    }
}

// MARK: - ShimmerView

struct ShimmerView: View {
    var height: CGFloat
    var cornerRadius: CGFloat = 12
    @State private var phase: CGFloat = -0.8

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(Color.secondary.opacity(0.12))
            .overlay {
                GeometryReader { proxy in
                    LinearGradient(
                        colors: [
                            .clear,
                            Color.white.opacity(0.35),
                            .clear,
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                    .frame(width: proxy.size.width * 0.6)
                    .offset(x: proxy.size.width * phase)
                }
                .mask(RoundedRectangle(cornerRadius: cornerRadius))
            }
            .frame(height: height)
            .onAppear {
                withAnimation(.linear(duration: 1.2).repeatForever(autoreverses: false)) {
                    phase = 1.4
                }
            }
    }
}

private struct BubbleShape: InsettableShape {
    let isUser: Bool
    var insetAmount: CGFloat = 0

    func path(in rect: CGRect) -> Path {
        let r: CGFloat = 14
        let small: CGFloat = 4
        var path = Path()
        let b = rect.insetBy(dx: insetAmount, dy: insetAmount)

        if isUser {
            // User: all rounded except bottom-right is small
            path.addRoundedRect(
                in: b,
                cornerRadii: .init(topLeading: r, bottomLeading: r, bottomTrailing: small, topTrailing: r)
            )
        } else {
            // Agent: all rounded except bottom-left is small
            path.addRoundedRect(
                in: b,
                cornerRadii: .init(topLeading: small, bottomLeading: r, bottomTrailing: r, topTrailing: r)
            )
        }
        return path
    }

    func inset(by amount: CGFloat) -> BubbleShape {
        var s = self
        s.insetAmount += amount
        return s
    }
}

// MARK: - ZoneTypeIcon

func zoneTypeIcon(_ type: String) -> (String, Color) {
    switch type {
    case "home":    return ("house.fill", .green)
    case "lecture": return ("graduationcap.fill", .blue)
    case "study":   return ("book.fill", .indigo)
    case "gym":     return ("figure.run", .orange)
    default:        return ("mappin.circle.fill", .purple)
    }
}

// MARK: - Section Header Helper

struct SectionHeaderLabel: View {
    let title: String
    let icon: String
    let color: Color

    init(_ title: String, icon: String, color: Color = .primary) {
        self.title = title
        self.icon = icon
        self.color = color
    }

    var body: some View {
        Label(title, systemImage: icon)
            .font(.headline)
            .foregroundStyle(color)
    }
}

// MARK: - Status Color Helpers

func macStatusColor(_ status: String?) -> Color {
    switch status {
    case "online", "online_idle": return .green
    case "paused", "degraded":    return .orange
    case "offline":               return .red
    default:                      return .secondary
    }
}

func healthColor(_ status: String?) -> Color {
    switch status {
    case "ok":       return .green
    case "degraded": return .orange
    default:         return .red
    }
}

func permissionColor(_ status: String) -> Color {
    switch status.lowercased() {
    case "granted":              return .green
    case "denied", "restricted": return .red
    default:                     return .orange
    }
}
