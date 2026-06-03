import AppKit
import Vision

/// Manages screen capture and OCR for the Calm Capture overlay.
/// Uses CGWindowListCreateImage for screenshots and Apple Vision VNRecognizeTextRequest for OCR.
/// Designed for a < 300ms latency budget (screenshot + OCR combined).
final class ScreenCaptureManager {

    /// Metadata about the captured window.
    struct CaptureMetadata {
        let appName: String
        let windowTitle: String
    }

    // MARK: - Window Capture

    /// Capture the frontmost application window as a CGImage.
    /// Requires Screen Recording permission in System Preferences.
    func captureActiveWindow() -> (image: CGImage, metadata: CaptureMetadata)? {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        let windowList = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] ?? []

        guard let frontApp = NSWorkspace.shared.frontmostApplication else {
            NSLog("[ScreenCapture] No frontmost application found")
            return nil
        }
        let pid = frontApp.processIdentifier
        let appName = frontApp.localizedName ?? "Unknown"

        // Find the frontmost window belonging to the active app (layer 0 = normal windows)
        guard let targetWindow = windowList.first(where: {
            ($0[kCGWindowOwnerPID as String] as? Int32) == pid &&
            ($0[kCGWindowLayer as String] as? Int) == 0
        }) else {
            NSLog("[ScreenCapture] No window found for PID \(pid) (\(appName))")
            return nil
        }

        guard let windowID = targetWindow[kCGWindowNumber as String] as? CGWindowID else {
            NSLog("[ScreenCapture] Could not get window ID")
            return nil
        }

        let windowTitle = (targetWindow[kCGWindowName as String] as? String) ?? appName

        guard let image = CGWindowListCreateImage(
            .null,
            .optionIncludingWindow,
            windowID,
            [.boundsIgnoreFraming]
        ) else {
            NSLog("[ScreenCapture] CGWindowListCreateImage returned nil")
            return nil
        }

        let metadata = CaptureMetadata(appName: appName, windowTitle: windowTitle)
        return (image: image, metadata: metadata)
    }

    // MARK: - OCR

    /// Perform OCR on a CGImage using Apple Vision Framework.
    /// The completion handler is called on a background queue.
    func performOCR(image: CGImage, completion: @escaping (String) -> Void) {
        let request = VNRecognizeTextRequest { request, error in
            if let error = error {
                NSLog("[ScreenCapture] OCR error: \(error.localizedDescription)")
                completion("")
                return
            }
            guard let observations = request.results as? [VNRecognizedTextObservation] else {
                completion("")
                return
            }
            let text = observations
                .compactMap { $0.topCandidates(1).first?.string }
                .joined(separator: "\n")
            completion(text)
        }
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true

        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try handler.perform([request])
            } catch {
                NSLog("[ScreenCapture] VNImageRequestHandler error: \(error.localizedDescription)")
                completion("")
            }
        }
    }

    // MARK: - Convenience

    /// Capture the active window and perform OCR in one call.
    /// Calls completion on a background queue with (ocrText, metadata) or nil on failure.
    func captureAndOCR(completion: @escaping (String, CaptureMetadata) -> Void) {
        guard let result = captureActiveWindow() else {
            NSLog("[ScreenCapture] captureActiveWindow failed — is Screen Recording permission granted?")
            return
        }

        performOCR(image: result.image) { text in
            completion(text, result.metadata)
        }
    }

    // MARK: - Markdown Formatting

    /// Format raw OCR text as Markdown with context.
    func formatAsMarkdown(rawText: String, appName: String, windowTitle: String) -> String {
        let lines = rawText
            .components(separatedBy: "\n")
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }

        var md = "# Screen Capture: \(windowTitle)\n\n"
        md += "> Captured from **\(appName)** via OCR\n\n"
        md += lines.joined(separator: "\n\n")
        return md
    }
}
