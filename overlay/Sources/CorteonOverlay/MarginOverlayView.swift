import SwiftUI
import AppKit

// MARK: - MarginOverlayView

/// A persistent right-edge luminous margin strip that expands on hover to
/// reveal the top-3 recent insight titles.
struct MarginOverlayView: View {

    // Weak reference back to the hosting panel so we can toggle mouse events
    weak var panel: GhostPanel?

    // MARK: State
    @State private var isHovered:  Bool     = false
    @State private var insights:   [String] = []

    // MARK: Layout
    private let collapsedWidth: CGFloat = 30
    private let expandedWidth:  CGFloat = 200

    // MARK: Body

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                Spacer()

                ZStack(alignment: .trailing) {
                    // Luminous gradient line (always visible)
                    luminousGradient(height: geo.size.height)
                        .frame(width: 2)
                        .opacity(isHovered ? 0.6 : 0.15)

                    // Expanded panel
                    if isHovered {
                        expandedPanel(height: geo.size.height)
                            .transition(.move(edge: .trailing).combined(with: .opacity))
                    }
                }
                .frame(width: isHovered ? expandedWidth : collapsedWidth)
            }
        }
        .animation(.easeOut(duration: 0.3), value: isHovered)
        .onHover { hovering in
            isHovered = hovering
            panel?.setInteractive(hovering)
            if hovering {
                loadInsights()
            }
        }
    }

    // MARK: - Sub-views

    private func luminousGradient(height: CGFloat) -> some View {
        LinearGradient(
            gradient: Gradient(colors: [
                Color.white.opacity(0.6),
                Color(red: 0.35, green: 0.65, blue: 1.0).opacity(0.8),
                Color.white.opacity(0.6)
            ]),
            startPoint: .top,
            endPoint: .bottom
        )
        .frame(height: height)
    }

    private func expandedPanel(height: CGFloat) -> some View {
        VStack(alignment: .trailing, spacing: 12) {
            Text("Recent Insights")
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(Color.white.opacity(0.5))
                .padding(.top, 20)

            ForEach(insights.prefix(3), id: \.self) { insight in
                Text(insight)
                    .font(.system(size: 11))
                    .foregroundColor(Color.white.opacity(0.40))
                    .lineLimit(2)
                    .multilineTextAlignment(.trailing)
                    .padding(.horizontal, 10)
            }

            Spacer()
        }
        .frame(width: expandedWidth - 4)
        .background(
            VisualEffectView(material: .hudWindow, blendingMode: .behindWindow)
                .overlay(Color(white: 0.06, opacity: 0.75))
                .clipShape(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                )
        )
    }

    // MARK: - Data

    /// Loads insight titles from the shared ~/.corteon/recent_insights.json file.
    /// Falls back to empty list gracefully if the file is absent or malformed.
    private func loadInsights() {
        let url = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent(".corteon/recent_insights.json")

        guard
            let data   = try? Data(contentsOf: url),
            let titles = try? JSONDecoder().decode([String].self, from: data)
        else { return }

        withAnimation(.easeOut(duration: 0.2)) {
            insights = titles
        }
    }
}
