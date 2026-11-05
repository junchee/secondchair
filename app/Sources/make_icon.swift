// Draws the app icon: Jun's picture on a white rounded square, 1024 x 1024.
import AppKit
let source = NSImage(contentsOfFile: CommandLine.arguments[1])!
let size: CGFloat = 1024
let canvas = NSImage(size: NSSize(width: size, height: size))
canvas.lockFocus()
let bounds = NSRect(x: 50, y: 50, width: size - 100, height: size - 100)
let path = NSBezierPath(roundedRect: bounds, xRadius: 210, yRadius: 210)
NSColor.white.setFill()   // the picture has a white background of its own: a white square hides its edges
path.fill()
NSColor(calibratedWhite: 0, alpha: 0.10).setStroke()
path.lineWidth = 6
path.stroke()
let scale = min((size - 300) / source.size.width, (size - 300) / source.size.height)
let w = source.size.width * scale, h = source.size.height * scale
source.draw(in: NSRect(x: (size - w) / 2, y: (size - h) / 2, width: w, height: h), from: .zero, operation: .sourceOver,
            fraction: 1.0, respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high.rawValue])
canvas.unlockFocus()
let rep = NSBitmapImageRep(data: canvas.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
