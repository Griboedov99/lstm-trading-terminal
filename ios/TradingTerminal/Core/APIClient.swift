import Foundation

/// REST-клиент сервера-эмулятора (команды: ордера, режим, скорость, отчёт).
final class APIClient {
    static let shared = APIClient()

    private static let urlKey = "serverURL"
    static let defaultURL = "http://localhost:8000"

    var baseURL: URL {
        let raw = UserDefaults.standard.string(forKey: Self.urlKey) ?? Self.defaultURL
        return URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)) ?? URL(string: Self.defaultURL)!
    }

    func setBaseURL(_ string: String) {
        UserDefaults.standard.set(string, forKey: Self.urlKey)
    }

    /// ws://host:port/ws/SYMBOL
    func webSocketURL(symbol: String) -> URL {
        var comps = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        comps.scheme = (comps.scheme == "https") ? "wss" : "ws"
        comps.path = "/ws/\(symbol)"
        return comps.url!
    }

    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 8
        return URLSession(configuration: cfg)
    }()

    enum APIError: LocalizedError {
        case server(String)
        var errorDescription: String? {
            switch self { case .server(let m): return m }
        }
    }

    private func request(_ path: String, method: String = "GET", body: [String: Any]? = nil,
                         completion: @escaping (Result<Data, Error>) -> Void) {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        if let body = body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        session.dataTask(with: req) { data, response, error in
            DispatchQueue.main.async {
                if let error = error { return completion(.failure(error)) }
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                let data = data ?? Data()
                guard (200..<300).contains(code) else {
                    let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                    let msg = (obj?["detail"] as? String) ?? "HTTP \(code)"
                    return completion(.failure(APIError.server(msg)))
                }
                completion(.success(data))
            }
        }.resume()
    }

    // MARK: - Эндпоинты

    func symbols(completion: @escaping (Result<[SymbolInfo], Error>) -> Void) {
        request("api/symbols") { result in
            completion(result.flatMap { data in
                Result { try JSONDecoder.api.decode([SymbolInfo].self, from: data) }
            })
        }
    }

    func placeOrder(symbol: String, side: String, qty: Double, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/order", method: "POST", body: ["side": side, "qty": qty]) { completion($0.map { _ in () }) }
    }

    func closePosition(symbol: String, id: Int, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/close/\(id)", method: "POST") { completion($0.map { _ in () }) }
    }

    func closeAll(symbol: String, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/close_all", method: "POST") { completion($0.map { _ in () }) }
    }

    func setMode(symbol: String, mode: String, qty: Double, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/mode", method: "POST", body: ["mode": mode, "qty": qty]) { completion($0.map { _ in () }) }
    }

    func setSpeed(symbol: String, candleSeconds: Double, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/speed", method: "POST", body: ["candle_seconds": candleSeconds]) { completion($0.map { _ in () }) }
    }

    func resetAccount(symbol: String, completion: @escaping (Result<Void, Error>) -> Void) {
        request("api/\(symbol)/reset", method: "POST") { completion($0.map { _ in () }) }
    }

    /// Отчёт о модели/бэктесте — произвольный JSON (ключи вида "MAPE_%"), поэтому без Codable.
    func report(completion: @escaping (Result<[String: Any], Error>) -> Void) {
        request("api/report") { result in
            completion(result.flatMap { data -> Result<[String: Any], Error> in
                Result<[String: Any], Error> {
                    guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                        throw APIError.server("неверный формат отчёта")
                    }
                    return obj
                }
            })
        }
    }
}
