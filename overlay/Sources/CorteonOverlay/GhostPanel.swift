import AppKit
import SwiftUI

/// A borderless, transparent, non-activating floating panel used as the
/// host surface for all SwiftUI overlay views.
final class GhostPanel: NSPanel {

    private var hostingView: NSView?

    // MARK: - Init

    init(frame: NSRect) {
        super.init(
            contentRect: frame,
            styleMask: [.nonactivatingPanel, .borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )

        level                 = .floating
        collectionBehavior    = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hidesOnDeactivate     = false
        backgroundColor       = .clear
        isOpaque              = false
        hasShadow             = false
        ignoresMouseEvents    = true
        isMovableByWindowBackground = false
        titleVisibility       = .hidden
        titlebarAppearsTransparent = true
    }

    // Required for NSPanel subclassing – panel can become key only when interactive
    override var canBecomeKey: Bool { !ignoresMouseEvents }
    override var canBecomeMain: Bool { false }

    // MARK: - Content

    /// Replaces the current hosted SwiftUI view with a new one.
    func setContent<V: View>(_ view: V) {
        // Remove old hosting view
        hostingView?.removeFromSuperview()

        let hosting = NSHostingView(rootView: view)
        hosting.frame = contentView?.bounds ?? .zero
        hosting.autoresizingMask = [.width, .height]
        hosting.translatesAutoresizingMaskIntoConstraints = false
        hosting.wantsLayer = true
        hosting.layer?.backgroundColor = NSColor.clear.cgColor

        contentView?.addSubview(hosting)
        if let cv = contentView {
            NSLayoutConstraint.activate([
                hosting.leadingAnchor.constraint(equalTo: cv.leadingAnchor),
                hosting.trailingAnchor.constraint(equalTo: cv.trailingAnchor),
                hosting.topAnchor.constraint(equalTo: cv.topAnchor),
                hosting.bottomAnchor.constraint(equalTo: cv.bottomAnchor)
            ])
        }
        hostingView = hosting
    }

    // MARK: - Interaction

    /// Toggle mouse-event pass-through.
    func setInteractive(_ interactive: Bool) {
        ignoresMouseEvents = !interactive
        if interactive {
            orderFront(nil)
            makeKey()
        }
    }

    // MARK: - Positioning

    /// Places the panel 20 px above the Dock in the bottom-right corner of the
    /// main screen, accounting for the menu bar and any safe-area insets.
    func positionBottomRight() {
        guard let screen = NSScreen.main else { return }
        let visibleFrame = screen.visibleFrame
        let margin: CGFloat = 20
        let origin = NSPoint(
            x: visibleFrame.maxX - frame.width - margin,
            y: visibleFrame.minY + margin
        )
        setFrameOrigin(origin)
    }
}
