import AppKit
import Foundation

let fileManager = FileManager.default
let repoRoot = URL(fileURLWithPath: fileManager.currentDirectoryPath)
let iconDirectory = repoRoot
    .appendingPathComponent("mac_native", isDirectory: true)
    .appendingPathComponent("LifeManager/Assets.xcassets/AppIcon.appiconset", isDirectory: true)

let iconSizes = [16, 32, 64, 128, 256, 512, 1024]

try fileManager.createDirectory(at: iconDirectory, withIntermediateDirectories: true)

for size in iconSizes {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: size,
        pixelsHigh: size,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        fatalError("Unable to allocate bitmap for icon generation.")
    }

    bitmap.size = NSSize(width: size, height: size)

    guard let graphicsContext = NSGraphicsContext(bitmapImageRep: bitmap) else {
        fatalError("Unable to create graphics context for icon generation.")
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = graphicsContext
    let context = graphicsContext.cgContext

    let rect = CGRect(x: 0, y: 0, width: size, height: size)
    let inset = CGFloat(size) * 0.04
    let cardRect = rect.insetBy(dx: inset, dy: inset)
    let cornerRadius = CGFloat(size) * 0.22
    let clipPath = NSBezierPath(roundedRect: cardRect, xRadius: cornerRadius, yRadius: cornerRadius)
    clipPath.addClip()

    let colors = [
        NSColor(calibratedRed: 0.04, green: 0.09, blue: 0.19, alpha: 1.0).cgColor,
        NSColor(calibratedRed: 0.17, green: 0.25, blue: 0.55, alpha: 1.0).cgColor,
        NSColor(calibratedRed: 0.28, green: 0.36, blue: 0.78, alpha: 1.0).cgColor,
    ] as CFArray

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let gradient = CGGradient(colorsSpace: colorSpace, colors: colors, locations: [0.0, 0.55, 1.0])!
    context.drawLinearGradient(
        gradient,
        start: CGPoint(x: cardRect.minX, y: cardRect.minY),
        end: CGPoint(x: cardRect.maxX, y: cardRect.maxY),
        options: []
    )

    let glowRect = cardRect.insetBy(dx: CGFloat(size) * 0.1, dy: CGFloat(size) * 0.1)
    let glow = NSColor(calibratedWhite: 1.0, alpha: 0.08)
    context.setFillColor(glow.cgColor)
    context.fillEllipse(in: glowRect.offsetBy(dx: 0, dy: CGFloat(size) * 0.02))

    let waveform = NSBezierPath()
    waveform.lineCapStyle = .round
    waveform.lineJoinStyle = .round
    waveform.lineWidth = max(2.0, CGFloat(size) * 0.055)

    let x0 = cardRect.minX + cardRect.width * 0.15
    let x1 = cardRect.minX + cardRect.width * 0.34
    let x2 = cardRect.minX + cardRect.width * 0.43
    let x3 = cardRect.minX + cardRect.width * 0.50
    let x4 = cardRect.minX + cardRect.width * 0.57
    let x5 = cardRect.minX + cardRect.width * 0.68
    let x6 = cardRect.minX + cardRect.width * 0.85

    let midY = cardRect.midY
    let low = cardRect.minY + cardRect.height * 0.30
    let high = cardRect.minY + cardRect.height * 0.74

    waveform.move(to: CGPoint(x: x0, y: midY))
    waveform.line(to: CGPoint(x: x1, y: midY))
    waveform.line(to: CGPoint(x: x2, y: cardRect.minY + cardRect.height * 0.56))
    waveform.line(to: CGPoint(x: x3, y: high))
    waveform.line(to: CGPoint(x: x4, y: low))
    waveform.line(to: CGPoint(x: x5, y: midY))
    waveform.line(to: CGPoint(x: x6, y: midY))

    context.saveGState()
    context.setShadow(offset: .zero, blur: CGFloat(size) * 0.045, color: NSColor.white.withAlphaComponent(0.35).cgColor)
    NSColor.white.withAlphaComponent(0.95).setStroke()
    waveform.stroke()
    context.restoreGState()
    NSGraphicsContext.restoreGraphicsState()

    guard let pngData = bitmap.representation(using: .png, properties: [:]) else {
        fatalError("Unable to serialize icon PNG at size \(size).")
    }

    let outputURL = iconDirectory.appendingPathComponent("appicon_\(size).png")
    try pngData.write(to: outputURL)
}

print("Generated AppIcon assets in \(iconDirectory.path)")
