import SwiftUI

// MARK: - CapturePopoverView

/// Capture confirmation popup displayed after Cmd+Shift+K.
/// Shows title, word count, novelty score and lets the user attach a quick note.
/// Auto-dismisses after 7 seconds; animates in from the bottom-right.
struct CapturePopoverView: View {

    // MARK: Input
    let title:        String
    let wordCount:    Int
    let noveltyScore: Double     // prediction error, 0.0 – 1.0
    let captureId:    String
    let onNote:       (String) -> Void
    let onDismiss:    () -> Void

    // MARK: State
    @State private var noteText:      String = ""
    @State private var offsetY:       CGFloat = 60
    @State private var opacity:       Double  = 0.0
    @State private var dismissTask:   Task<Void, Never>? = nil
    @State private var submitted:     Bool    = false
    @FocusState private var noteFocused: Bool

    // MARK: Derived
    private var noveltyLabel: String {
        switch noveltyScore {
        case 0.0..<0.3: return "Familiar"
        case 0.3..<0.65: return "Interesting"
        default:          return "Novel ✦"
        }
    }

    private var noveltyColor: Color {
        switch noveltyScore {
        case 0.0..<0.3:  return Color.gray
        case 0.3..<0.65: return Color.orange
        default:          return Color(red: 0.35, green: 0.65, blue: 1.0)
        }
    }

    // MARK: Body

    var body: some View {
        ZStack {
            // Glassmorphic background
            VisualEffectView(material: .hudWindow, blendingMode: .behindWindow)
                .overlay(Color(white: 0.07, opacity: 0.88))
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

            VStack(alignment: .leading, spacing: 10) {

                // Header row
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Captured")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundColor(Color.white.opacity(0.4))
                        Text(title)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(Color.white.opacity(0.9))
                            .lineLimit(2)
                    }
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Color.white.opacity(0.4))
                    }
                    .buttonStyle(.plain)
                }

                // Stats row
                HStack(spacing: 16) {
                    statBadge(value: "\(wordCount)", label: "words")
                    statBadge(value: String(format: "%.0f%%", noveltyScore * 100), label: "novelty")
                    Text(noveltyLabel)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(noveltyColor)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(noveltyColor.opacity(0.15))
                        .clipShape(Capsule())
                }

                Divider()
                    .background(Color.white.opacity(0.12))

                // Note field
                VStack(alignment: .leading, spacing: 4) {
                    Text("Quick note (optional)")
                        .font(.system(size: 10))
                        .foregroundColor(Color.white.opacity(0.35))

                    TextField("e.g. connects to free energy principle…", text: $noteText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundColor(Color.white.opacity(0.8))
                        .focused($noteFocused)
                        .onSubmit { submitNote() }
                        .padding(8)
                        .background(Color.white.opacity(0.06))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }

                // Submit button
                HStack {
                    Spacer()
                    Button(action: submitNote) {
                        Text(submitted ? "✓ Saved" : "Save Note")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(submitted ? .green : .white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 6)
                            .background(submitted ? Color.green.opacity(0.2) : Color.white.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(submitted || noteText.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .padding(16)
        }
        .frame(width: 300, height: 220)
        .offset(y: offsetY)
        .opacity(opacity)
        .onAppear {
            animateIn()
            scheduleAutoDismiss()
        }
    }

    // MARK: - Sub-views

    private func statBadge(value: String, label: String) -> some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(Color.white.opacity(0.85))
            Text(label)
                .font(.system(size: 9))
                .foregroundColor(Color.white.opacity(0.4))
        }
    }

    // MARK: - Behaviour

    private func animateIn() {
        withAnimation(.spring(response: 0.45, dampingFraction: 0.75)) {
            offsetY = 0
            opacity = 1.0
        }
    }

    private func scheduleAutoDismiss() {
        dismissTask = Task {
            try? await Task.sleep(nanoseconds: 7_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run { dismiss() }
        }
    }

    private func submitNote() {
        let note = noteText.trimmingCharacters(in: .whitespaces)
        guard !note.isEmpty, !submitted else { return }
        submitted = true
        onNote(note)
        dismissTask?.cancel()
        dismissTask = Task {
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            await MainActor.run { dismiss() }
        }
    }

    private func dismiss() {
        dismissTask?.cancel()
        withAnimation(.easeOut(duration: 0.35)) {
            opacity = 0
            offsetY = 40
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            onDismiss()
        }
    }
}

// MARK: - Preview

#if DEBUG
struct CapturePopoverView_Previews: PreviewProvider {
    static var previews: some View {
        CapturePopoverView(
            title:        "The Predictive Mind – Hohwy 2013",
            wordCount:    1342,
            noveltyScore: 0.72,
            captureId:    "preview-001",
            onNote:       { _ in },
            onDismiss:    {}
        )
        .background(Color.black)
        .previewLayout(.sizeThatFits)
    }
}
#endif
