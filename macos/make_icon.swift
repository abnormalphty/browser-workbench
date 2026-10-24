// Renders the app icon master (1024×1024 PNG): the 境 mark on the workbench green.
// Usage: swift make_icon.swift OUTPUT.png
import AppKit

let output = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon-1024.png"
let size = 1024
guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                                    hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)

// Apple's grid: an 824 pt body centred in the 1024 canvas, ~185 pt corner radius.
let body = NSRect(x: 100, y: 100, width: 824, height: 824)
let shape = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)
NSGraphicsContext.current?.saveGraphicsState()
let shadow = NSShadow()
shadow.shadowColor = NSColor(white: 0, alpha: 0.28)
shadow.shadowOffset = NSSize(width: 0, height: -12)
shadow.shadowBlurRadius = 28
shadow.set()
NSColor(srgbRed: 0x21/255, green: 0x64/255, blue: 0x4e/255, alpha: 1).setFill()
shape.fill()
NSGraphicsContext.current?.restoreGraphicsState()
NSGradient(starting: NSColor(srgbRed: 0x2a/255, green: 0x78/255, blue: 0x5f/255, alpha: 1),
           ending: NSColor(srgbRed: 0x17/255, green: 0x4d/255, blue: 0x3d/255, alpha: 1))?.draw(in: shape, angle: -90)

// A paper-coloured window frame behind the character echoes the "workspace" idea.
let frame = NSBezierPath(roundedRect: body.insetBy(dx: 150, dy: 150), xRadius: 64, yRadius: 64)
frame.lineWidth = 20
NSColor(white: 1, alpha: 0.16).setStroke()
frame.stroke()

let font = NSFont(name: "PingFangSC-Semibold", size: 430) ?? NSFont.systemFont(ofSize: 430, weight: .semibold)
let paragraph = NSMutableParagraphStyle()
paragraph.alignment = .center
let text = NSAttributedString(string: "境", attributes: [.font: font, .foregroundColor: NSColor(srgbRed: 0.97, green: 0.98, blue: 0.96, alpha: 1), .paragraphStyle: paragraph])
let bounds = text.boundingRect(with: NSSize(width: 1024, height: 1024), options: [.usesLineFragmentOrigin, .usesFontLeading])
text.draw(in: NSRect(x: 0, y: (1024 - bounds.height) / 2 - 18, width: 1024, height: bounds.height))

NSGraphicsContext.restoreGraphicsState()
guard let png = bitmap.representation(using: .png, properties: [:]) else { exit(1) }
try png.write(to: URL(fileURLWithPath: output))
