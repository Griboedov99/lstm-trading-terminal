import Foundation

/// WebSocket-подписка на поток свечей с автоматическим переподключением.
final class StreamClient: NSObject {
    enum State: Equatable {
        case disconnected, connecting, connected
        case failed(String)
    }

    var onMessage: ((StreamMessage) -> Void)?
    var onStateChange: ((State) -> Void)?

    private(set) var state: State = .disconnected {
        didSet { if state != oldValue { let s = state; DispatchQueue.main.async { self.onStateChange?(s) } } }
    }

    private var task: URLSessionWebSocketTask?
    private var session: URLSession?
    private var url: URL?
    private var pingTimer: Timer?
    private var reconnectDelay: TimeInterval = 1
    private var generation = 0          // защита от «старых» колбэков после переподключения
    private var wantsConnection = false

    func connect(to url: URL) {
        disconnect()
        self.url = url
        wantsConnection = true
        open()
    }

    func disconnect() {
        wantsConnection = false
        generation += 1
        pingTimer?.invalidate()
        pingTimer = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        session?.invalidateAndCancel()
        session = nil
        state = .disconnected
    }

    private func open() {
        guard let url = url else { return }
        generation += 1
        let gen = generation
        state = .connecting
        // все колбэки — на главной очереди, поэтому состояние не требует синхронизации
        let s = URLSession(configuration: .default, delegate: self, delegateQueue: OperationQueue.main)
        session = s
        let t = s.webSocketTask(with: url)
        t.maximumMessageSize = 16 * 1024 * 1024
        task = t
        t.resume()
        receive(gen)
        DispatchQueue.main.async {
            self.pingTimer?.invalidate()
            self.pingTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
                self?.task?.send(.string("ping")) { _ in }
            }
        }
    }

    private func receive(_ gen: Int) {
        task?.receive { [weak self] result in
            guard let self = self, gen == self.generation else { return }
            switch result {
            case .success(let message):
                if self.state != .connected {
                    self.state = .connected
                    self.reconnectDelay = 1
                }
                let data: Data?
                switch message {
                case .string(let text): data = text.data(using: .utf8)
                case .data(let d): data = d
                @unknown default: data = nil
                }
                if let data = data {
                    do {
                        let msg = try StreamMessage.decode(data)
                        DispatchQueue.main.async { self.onMessage?(msg) }
                    } catch {
                        print("decode error:", error)
                    }
                }
                self.receive(gen)
            case .failure(let error):
                self.handleFailure(error.localizedDescription, gen: gen)
            }
        }
    }

    private func handleFailure(_ text: String, gen: Int) {
        guard gen == generation, wantsConnection else { return }
        state = .failed(text)
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, 10)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, gen == self.generation, self.wantsConnection else { return }
            self.task?.cancel()
            self.session?.invalidateAndCancel()
            self.open()
        }
    }
}

extension StreamClient: URLSessionWebSocketDelegate {
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        state = .connected
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        handleFailure("соединение закрыто", gen: generation)
    }
}
