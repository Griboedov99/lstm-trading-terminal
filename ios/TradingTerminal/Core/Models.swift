import Foundation

// MARK: - Модели данных, которые присылает сервер (JSON, snake_case → camelCase)

struct Candle: Codable, Equatable {
    let t: Int          // unix-время открытия свечи, сек
    var o: Double
    var h: Double
    var l: Double
    var c: Double
    var v: Double

    var isBullish: Bool { c >= o }
    var date: Date { Date(timeIntervalSince1970: TimeInterval(t)) }
}

struct PredictedCandle: Codable, Equatable {
    let open: Double
    let high: Double
    let low: Double
    let close: Double
}

struct Signal: Codable, Equatable {
    let action: String              // BUY / SELL / HOLD
    let confidence: Double          // max(P(up), 1 − P(up))
    let pUp: Double
    let expectedReturn: Double      // log(C_{t+1}/C_t)
    let expectedReturnPct: Double?
    let predicted: PredictedCandle
    let basedOn: Int
    let model: String
    let onlineHitRate: Double?
    let onlineScored: Int?

    enum Action { case buy, sell, hold }
    var kind: Action {
        switch action.uppercased() {
        case "BUY": return .buy
        case "SELL": return .sell
        default: return .hold
        }
    }
}

struct Position: Codable, Equatable {
    let id: Int
    let side: String                // long / short
    let qty: Double
    let entryPrice: Double
    let entryTime: Int
    let openedBy: String
    var currentPrice: Double?
    var pnl: Double

    var isLong: Bool { side == "long" }
}

struct Trade: Codable, Equatable {
    let id: Int
    let side: String
    let qty: Double
    let entryPrice: Double
    let exitPrice: Double
    let entryTime: Int
    let exitTime: Int
    let pnl: Double
    let openedBy: String
    let closedBy: String
}

struct EquityPoint: Codable, Equatable {
    let t: Int
    let equity: Double
}

struct AccountStats: Codable, Equatable {
    let trades: Int
    let winrate: Double
    let realizedPnl: Double
    let totalPnl: Double
    let returnPct: Double
    let maxDrawdownPct: Double
}

struct Account: Codable, Equatable {
    let initialBalance: Double
    var balance: Double
    var equity: Double
    var unrealizedPnl: Double
    let marginUsed: Double
    var price: Double
    var positions: [Position]
    let history: [Trade]
    let equityCurve: [EquityPoint]
    let stats: AccountStats
}

/// Облегчённое состояние счёта, приходит на каждом тике
struct AccountBrief: Codable {
    struct PositionPnl: Codable { let id: Int; let pnl: Double }
    let equity: Double
    let balance: Double
    let unrealizedPnl: Double
    let price: Double
    let positions: [PositionPnl]
}

struct BotLogEntry: Codable, Equatable {
    let t: Int
    let message: String
}

struct ModelInfo: Codable, Equatable {
    let name: String
    let lookback: Int
    let layers: Int
    let hidden: Int
    let pThr: Double
    let timeframe: String
}

struct SymbolInfo: Codable, Equatable {
    let symbol: String
    let title: String
    let timeframe: String
    let source: String
    let candleSeconds: Double
    let priceDigits: Int
    let defaultQty: Double
    let status: String
    let error: String?
    let model: ModelInfo
}

// MARK: - Сообщения WebSocket

struct SnapshotMessage: Codable {
    let symbol: String
    let title: String
    let timeframe: String
    let source: String
    let candleSeconds: Double
    let priceDigits: Int
    let defaultQty: Double
    let status: String
    let error: String?
    let model: ModelInfo
    let mode: String
    let autoQty: Double
    let candles: [Candle]
    let forming: Candle?
    let signal: Signal?
    let account: Account
    let botLog: [BotLogEntry]

    var info: SymbolInfo {
        SymbolInfo(symbol: symbol, title: title, timeframe: timeframe, source: source,
                   candleSeconds: candleSeconds, priceDigits: priceDigits, defaultQty: defaultQty,
                   status: status, error: error, model: model)
    }
}

struct TickMessage: Codable {
    let symbol: String
    let forming: Candle
    let account: AccountBrief
}

struct CandleMessage: Codable {
    let symbol: String
    let candle: Candle
    let signal: Signal?
    let account: Account
    let botLog: [BotLogEntry]
}

struct AccountMessage: Codable {
    let symbol: String
    let account: Account
    let mode: String
    let autoQty: Double
    let botLog: [BotLogEntry]
    let candleSeconds: Double?
}

enum StreamMessage {
    case snapshot(SnapshotMessage)
    case tick(TickMessage)
    case candle(CandleMessage)
    case account(AccountMessage)
    case error(String)
    case pong

    private struct Envelope: Decodable { let type: String; let message: String? }

    static func decode(_ data: Data) throws -> StreamMessage {
        let decoder = JSONDecoder.api
        let env = try decoder.decode(Envelope.self, from: data)
        switch env.type {
        case "snapshot": return .snapshot(try decoder.decode(SnapshotMessage.self, from: data))
        case "tick": return .tick(try decoder.decode(TickMessage.self, from: data))
        case "candle": return .candle(try decoder.decode(CandleMessage.self, from: data))
        case "account": return .account(try decoder.decode(AccountMessage.self, from: data))
        case "pong": return .pong
        default: return .error(env.message ?? "неизвестное сообщение: \(env.type)")
        }
    }
}

extension JSONDecoder {
    static var api: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }
}
