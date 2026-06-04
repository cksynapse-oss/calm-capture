import AppKit
import SwiftUI

// MARK: - IPC Message Types

struct IPCEnvelope: Decodable {
    let type: String
}

struct CaptureCompletePayload: Decodable {
    let captureId: String
    let title: String
    let wordCount: Int
    let predictionErrorScore: Double

    enum CodingKeys: String, CodingKey {
        case captureId         = "capture_id"
        case title
        case wordCount         = "word_count"
        case predictionErrorScore = "prediction_error_score"
    }
}

struct ResurfacePayload: Decodable {
    let captureId: String
    let title: String
    let excerpt: String
    let reason: String

    enum CodingKeys: String, CodingKey {
        case captureId = "capture_id"
        case title
        case excerpt
        case reason
    }
}

struct ToastPayload: Decodable {
    let message: String
}

// MARK: - AppDelegate

final class AppDelegate: NSObject, NSApplicationDelegate {

    var wsClient: WebSocketClient!
    var ghostPanel: GhostPanel?
    var marginPanel: GhostPanel?
    let screenCaptureManager = ScreenCaptureManager()

    // Track the currently displayed capture confirmation, if any
    private var activeCaptureId: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupPanels()

        wsClient = WebSocketClient()
        wsClient.onMessage = { [weak self] data in
            self?.handleMessage(data)
        }
        wsClient.connect()
    }

    // MARK: - Panels

    private func setupPanels() {
        // Right-edge luminous margin panel – full screen height, anchored to right edge
        let screen    = NSScreen.main ?? NSScreen.screens[0]
        let scrFrame  = screen.frame
        let marginW: CGFloat = 30
        let marginFrame = NSRect(
            x: scrFrame.maxX - marginW,
            y: scrFrame.minY,
            width: marginW,
            height: scrFrame.height
        )
        let mp = GhostPanel(frame: marginFrame)
        mp.setContent(MarginOverlayView(panel: mp))
        mp.orderFront(nil)
        marginPanel = mp

        // Ghost panel: sized for notification card, positioned bottom-right
        let ghostFrame = NSRect(x: 0, y: 0, width: 300, height: 260)
        let gp = GhostPanel(frame: ghostFrame)
        gp.positionBottomRight()
        ghostPanel = gp
    }

    // MARK: - Message Handling

    private func handleMessage(_ data: Data) {
        guard let envelope = try? JSONDecoder().decode(IPCEnvelope.self, from: data) else { return }

        DispatchQueue.main.async { [weak self] in
            switch envelope.type {
            case "CaptureComplete":
                self?.handleCaptureComplete(data)
            case "Resurface":
                self?.handleResuface(data)
            case "Toast":
                self?.handleToast(data)
            case "ScreenCaptureRequest":
                self?.handleScreenCaptureRequest()
            default:
                NSLog("[CorteonOverlay] Unknown message type: \(envelope.type)")
                break
            }
        }
    }

    private func handleCaptureComplete(_ data: Data) {
        guard let payload = try? JSONDecoder().decode(
            Wrapped<CaptureCompletePayload>.self, from: data
        ) else { return }

        let p = payload.payload
        activeCaptureId = p.captureId

        let view = CapturePopoverView(
            title: p.title,
            wordCount: p.wordCount,
            noveltyScore: p.predictionErrorScore,
            captureId: p.captureId,
            onNote: { [weak self] note in
                self?.sendNote(note, captureId: p.captureId)
            },
            onDismiss: { [weak self] in
                self?.ghostPanel?.orderOut(nil)
            }
        )

        ghostPanel?.setContent(view)
        ghostPanel?.setInteractive(true)
        ghostPanel?.positionBottomRight()
        ghostPanel?.orderFront(nil)
    }

    private func handleResuface(_ data: Data) {
        guard let payload = try? JSONDecoder().decode(
            Wrapped<ResurfacePayload>.self, from: data
        ) else { return }

        let p = payload.payload

        let view = GhostNotificationView(
            title: p.title,
            excerpt: p.excerpt,
            reason: p.reason,
            captureId: p.captureId,
            onFeedback: { [weak self] feedback in
                self?.sendFeedback(feedback, captureId: p.captureId)
                if feedback == "ignored" || feedback == "dismissed" {
                    DispatchQueue.main.async {
                        self?.ghostPanel?.orderOut(nil)
                    }
                }
            }
        )

        ghostPanel?.setContent(view)
        ghostPanel?.setInteractive(true)
        ghostPanel?.positionBottomRight()
        ghostPanel?.orderFront(nil)
    }

    private func handleToast(_ data: Data) {
        guard let payload = try? JSONDecoder().decode(
            Wrapped<ToastPayload>.self, from: data
        ) else { return }

        let message = payload.payload.message.replacingOccurrences(of: "\"", with: "\\\"")
        let script = "display notification \"\(message)\" with title \"Calm Capture\""
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    private func handleScreenCaptureRequest() {
        NSLog("[CorteonOverlay] ScreenCaptureRequest received — starting capture + OCR")

        screenCaptureManager.captureAndOCR { [weak self] ocrText, metadata in
            guard let self = self else { return }

            let iso8601 = ISO8601DateFormatter()
            iso8601.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let timestamp = iso8601.string(from: Date())

            // Build the ScreenCaptureResult message matching the Rust UIToDaemon enum
            let result: [String: Any] = [
                "type": "ScreenCaptureResult",
                "payload": [
                    "ocr_text": ocrText,
                    "app_name": metadata.appName,
                    "window_title": metadata.windowTitle,
                    "timestamp": timestamp
                ]
            ]

            guard let data = try? JSONSerialization.data(withJSONObject: result) else {
                NSLog("[CorteonOverlay] Failed to serialize ScreenCaptureResult")
                return
            }

            NSLog("[CorteonOverlay] ScreenCaptureResult: app=\(metadata.appName) title=\(metadata.windowTitle) ocrLen=\(ocrText.count)")
            self.wsClient.send(data)
        }
    }

    // MARK: - Outbound IPC

    private func sendFeedback(_ feedback: String, captureId: String) {
        let msg: [String: Any] = [
            "type":       "ui_feedback",
            "capture_id": captureId,
            "feedback":   feedback
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: msg) else { return }
        wsClient.send(data)
    }

    private func sendNote(_ note: String, captureId: String) {
        let msg: [String: Any] = [
            "type":       "user_note",
            "capture_id": captureId,
            "note":       note
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: msg) else { return }
        wsClient.send(data)
    }

}

// MARK: - Helpers

/// Generic wrapper that pulls `payload` out of the top-level JSON object
/// alongside the `type` discriminator.
private struct Wrapped<T: Decodable>: Decodable {
    let type: String
    let payload: T
}
