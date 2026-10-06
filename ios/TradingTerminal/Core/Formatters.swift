import Foundation

enum Fmt {
    static func price(_ v: Double, digits: Int) -> String {
        String(format: "%.\(digits)f", v)
    }

    static func money(_ v: Double, sign: Bool = false) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = 2
        f.groupingSeparator = " "
        f.decimalSeparator = ","
        let s = f.string(from: NSNumber(value: abs(v))) ?? String(format: "%.2f", abs(v))
        let prefix = v < 0 ? "−" : (sign && v > 0 ? "+" : "")
        return "\(prefix)$\(s)"
    }

    static func percent(_ v: Double, digits: Int = 1, sign: Bool = false) -> String {
        let s = String(format: "%.\(digits)f%%", abs(v))
        if v < 0 { return "−" + s }
        return (sign && v > 0 ? "+" : "") + s
    }

    static func qty(_ v: Double) -> String {
        if v >= 1000 && v.truncatingRemainder(dividingBy: 1000) == 0 { return "\(Int(v / 1000))K" }
        if v == v.rounded() { return String(Int(v)) }
        return String(format: "%g", v)
    }

    private static let timeF: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "dd.MM HH:mm"; f.timeZone = TimeZone(identifier: "UTC"); return f
    }()
    private static let dayF: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "dd.MM.yy"; f.timeZone = TimeZone(identifier: "UTC"); return f
    }()

    /// Время свечи: для дневок — дата, для внутридневных — дата и время (UTC, как в данных)
    static func time(_ t: Int, daily: Bool) -> String {
        let d = Date(timeIntervalSince1970: TimeInterval(t))
        return daily ? dayF.string(from: d) : timeF.string(from: d)
    }
}
