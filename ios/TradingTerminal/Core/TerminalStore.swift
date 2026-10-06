import Foundation

extension Notification.Name {
    /// userInfo["kind"]: TerminalStore.Change
    static let terminalStoreDidChange = Notification.Name("terminalStoreDidChange")
}

/// Единое состояние терминала; экраны подписываются на .terminalStoreDidChange.
final class TerminalStore {
    static let shared = TerminalStore()

    enum Change: String {
        case connection, snapshot, tick, candle, account, symbols
    }

    private(set) var symbols: [SymbolInfo] = []
    private(set) var symbol: String = UserDefaults.standard.string(forKey: "symbol") ?? "EURUSD"
    private(set) var info: SymbolInfo?
    private(set) var candles: [Candle] = []
    private(set) var forming: Candle?
    private(set) var signal: Signal?
    private(set) var account: Account?
    private(set) var mode: String = "manual"
    private(set) var autoQty: Double = 0
    private(set) var botLog: [BotLogEntry] = []
    private(set) var connection: StreamClient.State = .disconnected
    private(set) var lastSignalChange: Date?

    private let stream = StreamClient()
    private let maxCandles = 600

    var isAuto: Bool { mode == "auto" }
    var digits: Int { info?.priceDigits ?? 5 }
    var lastPrice: Double? { forming?.c ?? candles.last?.c }

    private init() {
        stream.onStateChange = { [weak self] state in
            self?.connection = state
            self?.post(.connection)
        }
        stream.onMessage = { [weak self] msg in self?.apply(msg) }
    }

    // MARK: - Подключение

    func connect() {
        stream.connect(to: APIClient.shared.webSocketURL(symbol: symbol))
        loadSymbols()
    }

    func reconnect() {
        candles = []; forming = nil; signal = nil; account = nil; info = nil; botLog = []
        post(.snapshot)
        connect()
    }

    func select(symbol: String) {
        guard symbol != self.symbol else { return }
        self.symbol = symbol
        UserDefaults.standard.set(symbol, forKey: "symbol")
        reconnect()
    }

    func loadSymbols() {
        APIClient.shared.symbols { [weak self] result in
            if case .success(let list) = result {
                self?.symbols = list
                self?.post(.symbols)
            }
        }
    }

    // MARK: - Применение сообщений

    private func apply(_ msg: StreamMessage) {
        switch msg {
        case .snapshot(let s):
            info = s.info
            candles = Array(s.candles.suffix(maxCandles))
            forming = s.forming
            setSignal(s.signal)
            account = s.account
            mode = s.mode
            autoQty = s.autoQty
            botLog = s.botLog
            post(.snapshot)
        case .tick(let t):
            guard t.symbol == symbol else { return }
            forming = t.forming
            if var acc = account {
                acc.equity = t.account.equity
                acc.balance = t.account.balance
                acc.unrealizedPnl = t.account.unrealizedPnl
                acc.price = t.account.price
                let pnl = Dictionary(uniqueKeysWithValues: t.account.positions.map { ($0.id, $0.pnl) })
                acc.positions = acc.positions.map { p in
                    var p = p
                    if let v = pnl[p.id] { p.pnl = v }
                    p.currentPrice = t.account.price
                    return p
                }
                account = acc
            }
            post(.tick)
        case .candle(let c):
            guard c.symbol == symbol else { return }
            forming = nil
            if let last = candles.last, last.t == c.candle.t {
                candles[candles.count - 1] = c.candle
            } else {
                candles.append(c.candle)
                if candles.count > maxCandles { candles.removeFirst(candles.count - maxCandles) }
            }
            setSignal(c.signal)
            account = c.account
            botLog = c.botLog
            post(.candle)
        case .account(let a):
            guard a.symbol == symbol else { return }
            account = a.account
            mode = a.mode
            autoQty = a.autoQty
            botLog = a.botLog
            post(.account)
        case .error(let text):
            connection = .failed(text)
            post(.connection)
        case .pong:
            break
        }
    }

    private func setSignal(_ s: Signal?) {
        if s?.action != signal?.action { lastSignalChange = Date() }
        signal = s
    }

    private func post(_ change: Change) {
        NotificationCenter.default.post(name: .terminalStoreDidChange, object: self, userInfo: ["kind": change])
    }

    // MARK: - Команды

    func order(side: String, qty: Double, completion: @escaping (Error?) -> Void) {
        APIClient.shared.placeOrder(symbol: symbol, side: side, qty: qty) { completion($0.error) }
    }

    func close(positionId: Int, completion: @escaping (Error?) -> Void) {
        APIClient.shared.closePosition(symbol: symbol, id: positionId) { completion($0.error) }
    }

    func closeAll(completion: @escaping (Error?) -> Void) {
        APIClient.shared.closeAll(symbol: symbol) { completion($0.error) }
    }

    func setMode(auto: Bool, qty: Double, completion: @escaping (Error?) -> Void) {
        APIClient.shared.setMode(symbol: symbol, mode: auto ? "auto" : "manual", qty: qty) { completion($0.error) }
    }

    func setSpeed(_ seconds: Double, completion: @escaping (Error?) -> Void) {
        APIClient.shared.setSpeed(symbol: symbol, candleSeconds: seconds) { completion($0.error) }
    }

    func resetAccount(completion: @escaping (Error?) -> Void) {
        APIClient.shared.resetAccount(symbol: symbol) { completion($0.error) }
    }
}

extension Result {
    var error: Failure? {
        if case .failure(let e) = self { return e }
        return nil
    }
}
