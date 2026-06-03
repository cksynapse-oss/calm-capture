import Foundation

// MARK: - IPC Message Types (typed structs matching daemon protocol)

/// Outer envelope — every message from the daemon carries a `type` field.
struct DaemonMessage: Decodable {
    let type: String
}

/// Sent after Cmd+Shift+K successfully captures a page.
struct CaptureCompleteMessage: Decodable {
    let type:                 String
    let captureId:            String
    let title:                String
    let wordCount:            Int
    let predictionErrorScore: Double

    enum CodingKeys: String, CodingKey {
        case type
        case captureId            = "capture_id"
        case title
        case wordCount            = "word_count"
        case predictionErrorScore = "prediction_error_score"
    }
}

/// Sent when the inference engine decides to resurface a memory.
struct ResurfaceMessage: Decodable {
    let type:      String
    let captureId: String
    let title:     String
    let excerpt:   String
    let reason:    String

    enum CodingKeys: String, CodingKey {
        case type
        case captureId = "capture_id"
        case title
        case excerpt
        case reason
    }
}

/// A short ephemeral notification string.
struct ToastMessage: Decodable {
    let type:    String
    let message: String
}

// MARK: - WebSocketClient

/// Manages a persistent WebSocket connection to the Calm Capture daemon.
/// Reconnects automatically with a 3-second back-off on any failure.
final class WebSocketClient: ObservableObject {

    // MARK: Configuration
    private let url = URL(string: "ws://localhost:9741/ui")!
    private let reconnectDelay: TimeInterval = 3.0

    // MARK: Public Callback
    /// Called on the main queue with the raw message Data whenever a message arrives.
    var onMessage: ((Data) -> Void)?

    // MARK: Private State
    private var urlSession: URLSession!
    private var webSocketTask: URLSessionWebSocketTask?
    private var isConnected = false
    private var shouldReconnect = true
    private var isReconnecting = false

    // MARK: Init

    init() {
        urlSession = URLSession(configuration: .default)
    }

    // MARK: - Public API

    func connect() {
        shouldReconnect = true
        openConnection()
    }

    func disconnect() {
        shouldReconnect = false
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        isConnected = false
    }

    /// Send raw data over the WebSocket. Silently drops if not connected.
    func send(_ data: Data) {
        guard isConnected, let task = webSocketTask else { return }
        task.send(.data(data)) { [weak self] error in
            if let error = error {
                NSLog("[CorteonWS] Send error: \(error.localizedDescription)")
                self?.scheduleReconnect()
            }
        }
    }

    // MARK: - Private

    private func openConnection() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)

        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        request.setValue("CorteonOverlay/1.0", forHTTPHeaderField: "User-Agent")

        let task = urlSession.webSocketTask(with: request)
        webSocketTask = task
        task.resume()

        // Send path-registration frame (daemon requires this as the first message)
        task.send(.string(#"{"path":"/ui"}"#)) { [weak self] error in
            if let error = error {
                NSLog("[CorteonWS] Registration frame error: \(error.localizedDescription)")
                self?.scheduleReconnect()
                return
            }
            NSLog("[CorteonWS] Registered on /ui path")
        }

        isConnected = true
        NSLog("[CorteonWS] Connecting to \(url)…")
        receiveNextMessage()
    }

    private func receiveNextMessage() {
        webSocketTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                self?.handleReceived(message)
                self?.receiveNextMessage()   // chain to next
            case .failure(let error):
                NSLog("[CorteonWS] Receive error: \(error.localizedDescription)")
                self?.isConnected = false
                self?.scheduleReconnect()
            }
        }
    }

    private func handleReceived(_ message: URLSessionWebSocketTask.Message) {
        let data: Data
        switch message {
        case .data(let d):
            data = d
        case .string(let s):
            guard let d = s.data(using: .utf8) else { return }
            data = d
        @unknown default:
            return
        }

        DispatchQueue.main.async { [weak self] in
            self?.onMessage?(data)
        }
    }

    private func scheduleReconnect() {
        guard shouldReconnect, !isReconnecting else { return }
        isReconnecting = true
        NSLog("[CorteonWS] Reconnecting in \(reconnectDelay)s…")
        DispatchQueue.main.asyncAfter(deadline: .now() + reconnectDelay) { [weak self] in
            guard let self, self.shouldReconnect else { return }
            self.isReconnecting = false
            self.openConnection()
        }
    }
}
