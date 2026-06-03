import SwiftUI
import AppKit

// MARK: - VisualEffectView

/// NSViewRepresentable wrapper for NSVisualEffectView providing the glassmorphic backdrop.
struct VisualEffectView: NSViewRepresentable {
    var material: NSVisualEffectView.Material
    var blendingMode: NSVisualEffectView.BlendingMode

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material     = material
        view.blendingMode = blendingMode
        view.state        = .active
        view.wantsLayer   = true
        view.layer?.cornerRadius = 14
        view.layer?.masksToBounds = true
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material     = material
        nsView.blendingMode = blendingMode
    }
}

// MARK: - GhostNotificationView

/// Resurfaced-memory notification card that ghosts in, auto-dismisses, and
/// expands on tap to show full details with a dismiss button.
struct GhostNotificationView: View {

    // MARK: Input
    let title:     String
    let excerpt:   String
    let reason:    String
    let captureId: String
    let onFeedback: (String) -> Void

    // MARK: State
    @State private var opacity:      Double = 0.0
    @State private var isExpanded:   Bool   = false
    @State private var dismissTask:  Task<Void, Never>? = nil

    // MARK: Layout constants
    private let collapsedHeight: CGFloat = 120
    private let expandedHeight:  CGFloat = 240
    private let cardWidth:       CGFloat = 280

    // MARK: Body

    var body: some View {
        ZStack(alignment: .topTrailing) {
            // Background
            VisualEffectView(material: .hudWindow, blendingMode: .behindWindow)
                .overlay(Color(white: 0.08, opacity: 0.85))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

            // Content
            VStack(alignment: .leading, spacing: 6) {
                // Reason badge
                Text(reason)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(Color(red: 0.35, green: 0.65, blue: 1.0))
                    .lineLimit(1)

                // Title
                Text(title)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(Color.white.opacity(0.88))
                    .lineLimit(isExpanded ? 3 : 2)

                // Excerpt – only when expanded
                if isExpanded {
                    Text(excerpt)
                        .font(.system(size: 11))
                        .foregroundColor(Color.white.opacity(0.55))
                        .lineLimit(5)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                }

                Spacer()
            }
            .padding(14)
            .frame(width: cardWidth, height: isExpanded ? expandedHeight : collapsedHeight, alignment: .topLeading)

            // Dismiss button – only when expanded
            if isExpanded {
                Button {
                    fadeOut(feedback: "dismissed")
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundColor(Color.white.opacity(0.6))
                        .padding(8)
                }
                .buttonStyle(.plain)
                .transition(.opacity)
            }
        }
        .frame(width: cardWidth, height: isExpanded ? expandedHeight : collapsedHeight)
        .opacity(opacity)
        .onTapGesture {
            handleTap()
        }
        .onAppear {
            scheduleGhostIn()
        }
        .animation(.easeOut(duration: 0.25), value: isExpanded)
    }

    // MARK: - Animations

    private func scheduleGhostIn() {
        // Fade in to ghost opacity
        withAnimation(.easeIn(duration: 0.8)) {
            opacity = 0.25
        }

        // Schedule auto-dismiss after 5.8s
        dismissTask = Task {
            try? await Task.sleep(nanoseconds: 5_800_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                fadeOut(feedback: "ignored")
            }
        }
    }

    private func handleTap() {
        guard !isExpanded else { return }

        // Cancel auto-dismiss
        dismissTask?.cancel()
        dismissTask = nil

        withAnimation(.easeOut(duration: 0.3)) {
            isExpanded = true
            opacity    = 0.80
        }

        onFeedback("clicked")
    }

    private func fadeOut(feedback: String) {
        withAnimation(.easeOut(duration: 1.2)) {
            opacity = 0.0
        }
        onFeedback(feedback)
    }
}

// MARK: - Preview

#if DEBUG
struct GhostNotificationView_Previews: PreviewProvider {
    static var previews: some View {
        GhostNotificationView(
            title:     "Active Inference and the Free Energy Principle",
            excerpt:   "Karl Friston's framework suggests that biological agents minimise surprise by building generative models of their environment…",
            reason:    "High prediction error – relevant to current reading",
            captureId: "abc-123",
            onFeedback: { _ in }
        )
        .frame(width: 300, height: 260)
        .background(Color.black)
        .previewLayout(.sizeThatFits)
    }
}
#endif
