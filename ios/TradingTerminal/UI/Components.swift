import UIKit

/// Карточка-контейнер в стиле терминала.
class CardView: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = Theme.surface
        layer.cornerRadius = 12
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

/// Плитка «заголовок / значение» (баланс, эквити, P&L…).
final class StatTileView: UIView {
    let titleLabel = UILabel()
    let valueLabel = UILabel()

    init(title: String) {
        super.init(frame: .zero)
        titleLabel.text = title.uppercased()
        titleLabel.font = .systemFont(ofSize: 10, weight: .semibold)
        titleLabel.textColor = Theme.textSecondary
        valueLabel.font = Theme.mono(15, .semibold)
        valueLabel.textColor = Theme.textPrimary
        valueLabel.adjustsFontSizeToFitWidth = true
        valueLabel.minimumScaleFactor = 0.6
        valueLabel.text = "—"
        let stack = UIStackView(arrangedSubviews: [titleLabel, valueLabel])
        stack.axis = .vertical
        stack.spacing = 3
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func set(_ text: String, color: UIColor = Theme.textPrimary) {
        valueLabel.text = text
        valueLabel.textColor = color
    }
}

/// Горизонтальная полоса уверенности 0…100 %.
final class ConfidenceBar: UIView {
    private let fill = UIView()
    private var fillWidth: NSLayoutConstraint?
    private(set) var value: CGFloat = 0

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = Theme.surfaceHigh
        layer.cornerRadius = 4
        clipsToBounds = true
        fill.layer.cornerRadius = 4
        fill.translatesAutoresizingMaskIntoConstraints = false
        addSubview(fill)
        NSLayoutConstraint.activate([
            fill.leadingAnchor.constraint(equalTo: leadingAnchor),
            fill.topAnchor.constraint(equalTo: topAnchor),
            fill.bottomAnchor.constraint(equalTo: bottomAnchor),
            heightAnchor.constraint(equalToConstant: 8),
        ])
        set(0, color: Theme.hold, animated: false)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func set(_ v: CGFloat, color: UIColor, animated: Bool = true) {
        value = min(max(v, 0), 1)
        fillWidth?.isActive = false
        fillWidth = fill.widthAnchor.constraint(equalTo: widthAnchor, multiplier: max(value, 0.001))
        fillWidth?.isActive = true
        fill.backgroundColor = color
        if animated {
            UIView.animate(withDuration: 0.3) { self.layoutIfNeeded() }
        }
    }
}

/// Карточка рекомендации модели: BUY / SELL / HOLD + уверенность + прогноз.
final class SignalCardView: CardView {
    private let caption = UILabel()
    private let actionLabel = UILabel()
    private let confidenceLabel = UILabel()
    private let bar = ConfidenceBar()
    private let details = UILabel()
    private let badge = UIView()

    override init(frame: CGRect) {
        super.init(frame: frame)
        caption.text = "РЕКОМЕНДАЦИЯ LSTM"
        caption.font = .systemFont(ofSize: 11, weight: .semibold)
        caption.textColor = Theme.textSecondary

        actionLabel.font = .systemFont(ofSize: 30, weight: .heavy)
        actionLabel.text = "—"
        actionLabel.textColor = Theme.textSecondary

        confidenceLabel.font = Theme.mono(15, .semibold)
        confidenceLabel.textColor = Theme.textPrimary
        confidenceLabel.textAlignment = .right
        confidenceLabel.numberOfLines = 2

        details.font = Theme.mono(12)
        details.textColor = Theme.textSecondary
        details.numberOfLines = 0

        badge.layer.cornerRadius = 5
        badge.backgroundColor = Theme.textSecondary
        badge.translatesAutoresizingMaskIntoConstraints = false
        badge.widthAnchor.constraint(equalToConstant: 10).isActive = true
        badge.heightAnchor.constraint(equalToConstant: 10).isActive = true

        let titleRow = UIStackView(arrangedSubviews: [badge, caption])
        titleRow.spacing = 8
        titleRow.alignment = .center
        let mainRow = UIStackView(arrangedSubviews: [actionLabel, confidenceLabel])
        mainRow.alignment = .center
        let stack = UIStackView(arrangedSubviews: [titleRow, mainRow, bar, details])
        stack.axis = .vertical
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: topAnchor, constant: 14),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -14),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -14),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func update(signal: Signal?, digits: Int, lastClose: Double?) {
        guard let s = signal else {
            actionLabel.text = "—"
            actionLabel.textColor = Theme.textSecondary
            confidenceLabel.text = "модель\nпрогревается"
            details.text = "Нужна история ≥ lookback + 60 свечей"
            bar.set(0, color: Theme.hold)
            return
        }
        let color = Theme.color(for: s.kind)
        let changed = actionLabel.text != s.action
        actionLabel.text = s.action
        actionLabel.textColor = color
        badge.backgroundColor = color
        confidenceLabel.text = "уверенность\n\(Fmt.percent(s.confidence * 100))"
        bar.set(CGFloat(s.confidence), color: color)
        var lines = [
            "P(рост) \(Fmt.percent(s.pUp * 100, digits: 1))   ожид. Δ \(Fmt.percent(s.expectedReturn * 100, digits: 3, sign: true))",
            "прогноз C \(Fmt.price(s.predicted.close, digits: digits))  H \(Fmt.price(s.predicted.high, digits: digits))  L \(Fmt.price(s.predicted.low, digits: digits))",
        ]
        if let hr = s.onlineHitRate, let n = s.onlineScored, n > 0 {
            lines.append("точность направления онлайн: \(Fmt.percent(hr * 100)) на \(n) свечах")
        }
        details.text = lines.joined(separator: "\n")
        if changed {
            UIView.animate(withDuration: 0.15, animations: { self.actionLabel.transform = CGAffineTransform(scaleX: 1.15, y: 1.15) },
                           completion: { _ in UIView.animate(withDuration: 0.2) { self.actionLabel.transform = .identity } })
        }
    }
}

/// Мини-график кривой капитала.
final class EquityChartView: UIView {
    private var points: [Double] = []
    private var baseline: Double = 0

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        contentMode = .redraw
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func update(points: [Double], baseline: Double) {
        self.points = points
        self.baseline = baseline
        setNeedsDisplay()
    }

    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        guard points.count > 1 else {
            let s = "Кривая капитала появится после первых свечей" as NSString
            s.draw(at: CGPoint(x: 8, y: rect.midY - 8),
                   withAttributes: [.font: UIFont.systemFont(ofSize: 12), .foregroundColor: Theme.textSecondary])
            return
        }
        var lo = min(points.min()!, baseline), hi = max(points.max()!, baseline)
        if hi - lo < 1e-9 { hi += 1; lo -= 1 }
        let r = rect.insetBy(dx: 4, dy: 6)
        let xf = { (i: Int) -> CGFloat in r.minX + CGFloat(i) / CGFloat(self.points.count - 1) * r.width }
        let yf = { (v: Double) -> CGFloat in r.maxY - CGFloat((v - lo) / (hi - lo)) * r.height }

        ctx.setStrokeColor(Theme.textSecondary.withAlphaComponent(0.4).cgColor)
        ctx.setLineDash(phase: 0, lengths: [3, 3])
        ctx.move(to: CGPoint(x: r.minX, y: yf(baseline))); ctx.addLine(to: CGPoint(x: r.maxX, y: yf(baseline)))
        ctx.strokePath()
        ctx.setLineDash(phase: 0, lengths: [])

        let color = Theme.pnlColor(points.last! - baseline)
        let path = UIBezierPath()
        for (i, v) in points.enumerated() {
            let p = CGPoint(x: xf(i), y: yf(v))
            if i == 0 { path.move(to: p) } else { path.addLine(to: p) }
        }
        let fill = path.copy() as! UIBezierPath
        fill.addLine(to: CGPoint(x: r.maxX, y: r.maxY))
        fill.addLine(to: CGPoint(x: r.minX, y: r.maxY))
        fill.close()
        ctx.setFillColor(color.withAlphaComponent(0.12).cgColor)
        ctx.addPath(fill.cgPath); ctx.fillPath()
        ctx.setStrokeColor(color.cgColor)
        ctx.setLineWidth(2)
        ctx.addPath(path.cgPath); ctx.strokePath()
    }
}

extension UIViewController {
    func showError(_ error: Error) {
        let a = UIAlertController(title: "Ошибка", message: error.localizedDescription, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default))
        present(a, animated: true)
    }
}
