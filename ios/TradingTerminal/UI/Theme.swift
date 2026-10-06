import UIKit

/// Палитра терминала (тёмная тема, как у торговых платформ).
enum Theme {
    static let background = UIColor(red: 0.067, green: 0.075, blue: 0.094, alpha: 1)    // #111318
    static let surface = UIColor(red: 0.106, green: 0.118, blue: 0.145, alpha: 1)       // #1B1E25
    static let surfaceHigh = UIColor(red: 0.149, green: 0.165, blue: 0.200, alpha: 1)   // #262A33
    static let grid = UIColor(white: 1, alpha: 0.06)
    static let textPrimary = UIColor(white: 0.94, alpha: 1)
    static let textSecondary = UIColor(white: 0.60, alpha: 1)
    static let bull = UIColor(red: 0.149, green: 0.651, blue: 0.604, alpha: 1)          // #26A69A
    static let bear = UIColor(red: 0.937, green: 0.325, blue: 0.314, alpha: 1)          // #EF5350
    static let hold = UIColor(red: 0.98, green: 0.72, blue: 0.20, alpha: 1)             // #FAB833
    static let accent = UIColor(red: 0.36, green: 0.55, blue: 1.0, alpha: 1)            // #5C8CFF

    static func pnlColor(_ v: Double) -> UIColor {
        v > 0 ? bull : (v < 0 ? bear : textSecondary)
    }

    static func color(for action: Signal.Action) -> UIColor {
        switch action {
        case .buy: return bull
        case .sell: return bear
        case .hold: return hold
        }
    }

    static func mono(_ size: CGFloat, _ weight: UIFont.Weight = .regular) -> UIFont {
        UIFont.monospacedDigitSystemFont(ofSize: size, weight: weight)
    }
}
