import UIKit

/// График японских свечей на CoreGraphics.
/// * зелёная свеча — close > open (рост), красная — close < open (падение);
/// * тени — high/low, тело — open/close; внизу — объём;
/// * пунктирная «призрачная» свеча справа — прогноз LSTM на следующую свечу;
/// * pinch — масштаб, горизонтальный pan — прокрутка истории, долгое нажатие — перекрестие с OHLC.
final class CandleChartView: UIView, UIGestureRecognizerDelegate {

    struct PositionLine {
        let price: Double
        let isLong: Bool
        let label: String
    }

    // MARK: - Данные
    private(set) var candles: [Candle] = []
    private(set) var forming: Candle?
    private var prediction: PredictedCandle?
    private var predictionAction: Signal.Action = .hold
    private var positionLines: [PositionLine] = []
    private var digits = 5
    private var daily = false

    // MARK: - Вьюпорт
    private var spacing: CGFloat = 9            // ширина слота свечи, pt
    private var offset: CGFloat = 0             // сдвиг от последней свечи, в свечах
    private var crosshair: CGPoint?
    private let axisW: CGFloat = 64
    private let axisH: CGFloat = 20
    private let rightSlots: CGFloat = 3         // место справа под прогнозную свечу
    private var pinchStartSpacing: CGFloat = 9
    private var panStartOffset: CGFloat = 0

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = Theme.surface
        layer.cornerRadius = 12
        clipsToBounds = true
        isOpaque = false
        contentMode = .redraw

        let pinch = UIPinchGestureRecognizer(target: self, action: #selector(onPinch(_:)))
        let pan = UIPanGestureRecognizer(target: self, action: #selector(onPan(_:)))
        pan.delegate = self
        let press = UILongPressGestureRecognizer(target: self, action: #selector(onPress(_:)))
        press.minimumPressDuration = 0.25
        let doubleTap = UITapGestureRecognizer(target: self, action: #selector(onDoubleTap))
        doubleTap.numberOfTapsRequired = 2
        let recognizers: [UIGestureRecognizer] = [pinch, pan, press, doubleTap]
        for r in recognizers { addGestureRecognizer(r) }
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    // MARK: - API

    func update(candles: [Candle], forming: Candle?, prediction: PredictedCandle?, action: Signal.Action,
                positions: [PositionLine], digits: Int, daily: Bool) {
        let oldCount = self.candles.count
        if oldCount > 0, candles.count > oldCount, offset > 0.5,
           candles.first?.t == self.candles.first?.t || candles.count - oldCount < 5 {
            offset += CGFloat(candles.count - oldCount)     // пользователь листает историю — не «прыгаем»
        }
        if oldCount == 0 || candles.count < oldCount - 5 { offset = 0 }
        self.candles = candles
        self.forming = forming
        self.prediction = prediction
        self.predictionAction = action
        self.positionLines = positions
        self.digits = digits
        self.daily = daily
        setNeedsDisplay()
    }

    // MARK: - Геометрия

    private var series: [Candle] {
        if let f = forming, f.t != candles.last?.t { return candles + [f] }
        return candles
    }

    private var plotRect: CGRect {
        CGRect(x: 8, y: 10, width: bounds.width - axisW - 8, height: bounds.height - axisH - 10)
    }

    private var priceRect: CGRect {
        let r = plotRect
        return CGRect(x: r.minX, y: r.minY, width: r.width, height: r.height * 0.80)
    }

    private var volumeRect: CGRect {
        let r = plotRect
        return CGRect(x: r.minX, y: r.minY + r.height * 0.84, width: r.width, height: r.height * 0.16)
    }

    private func x(for i: Int, count n: Int) -> CGFloat {
        plotRect.maxX - (CGFloat(n - 1 - i) + rightSlots - offset) * spacing - spacing / 2
    }

    private func index(atX px: CGFloat, count n: Int) -> Int {
        let k = (plotRect.maxX - spacing / 2 - px) / spacing - rightSlots + offset
        return n - 1 - Int(k.rounded())
    }

    // MARK: - Отрисовка

    override func draw(_ rect: CGRect) {
        guard let ctx = UIGraphicsGetCurrentContext() else { return }
        let data = series
        let n = data.count
        guard n > 0, plotRect.width > 20, plotRect.height > 20 else {
            drawCentered("Ожидание котировок…", in: bounds)
            return
        }
        let pr = priceRect, vr = volumeRect

        // видимый диапазон
        var lo = Int.max, hi = Int.min
        for i in 0..<n {
            let cx = x(for: i, count: n)
            if cx >= pr.minX - spacing && cx <= pr.maxX + spacing { lo = min(lo, i); hi = max(hi, i) }
        }
        guard lo <= hi else { return }
        let visible = data[lo...hi]
        var minP = visible.map(\.l).min() ?? 0
        var maxP = visible.map(\.h).max() ?? 1
        let showPrediction = prediction != nil && offset < rightSlots - 0.5
        if showPrediction, let p = prediction { minP = min(minP, p.low); maxP = max(maxP, p.high) }
        if maxP - minP < 1e-12 { maxP += 1e-4; minP -= 1e-4 }
        let pad = (maxP - minP) * 0.08
        minP -= pad; maxP += pad
        let y: (Double) -> CGFloat = { p in pr.minY + CGFloat((maxP - p) / (maxP - minP)) * pr.height }
        let maxV = max(visible.map(\.v).max() ?? 1, 1e-9)

        // сетка + шкала цен
        let labelAttrs: [NSAttributedString.Key: Any] = [.font: Theme.mono(10), .foregroundColor: Theme.textSecondary]
        ctx.setLineWidth(1)
        for k in 0...5 {
            let p = minP + (maxP - minP) * Double(k) / 5
            let yy = y(p).rounded() + 0.5
            ctx.setStrokeColor(Theme.grid.cgColor)
            ctx.move(to: CGPoint(x: pr.minX, y: yy)); ctx.addLine(to: CGPoint(x: pr.maxX, y: yy)); ctx.strokePath()
            (Fmt.price(p, digits: digits) as NSString).draw(at: CGPoint(x: pr.maxX + 6, y: yy - 7), withAttributes: labelAttrs)
        }
        // шкала времени
        let step = max(1, Int(ceil(76 / spacing)))
        for i in lo...hi where i % step == 0 {
            let cx = x(for: i, count: n)
            ctx.setStrokeColor(Theme.grid.cgColor)
            ctx.move(to: CGPoint(x: cx, y: pr.minY)); ctx.addLine(to: CGPoint(x: cx, y: vr.maxY)); ctx.strokePath()
            let s = Fmt.time(data[i].t, daily: daily) as NSString
            let w = s.size(withAttributes: labelAttrs).width
            s.draw(at: CGPoint(x: cx - w / 2, y: plotRect.maxY + 4), withAttributes: labelAttrs)
        }

        // свечи и объём
        let bodyW = max(1, spacing * 0.7)
        ctx.saveGState()
        ctx.clip(to: CGRect(x: plotRect.minX, y: 0, width: plotRect.width, height: bounds.height))
        for i in lo...hi {
            let c = data[i]
            let cx = x(for: i, count: n)
            let color = c.isBullish ? Theme.bull : Theme.bear
            // тень
            ctx.setStrokeColor(color.cgColor)
            ctx.setLineWidth(max(1, spacing * 0.12))
            ctx.move(to: CGPoint(x: cx, y: y(c.h))); ctx.addLine(to: CGPoint(x: cx, y: y(c.l))); ctx.strokePath()
            // тело
            let top = y(max(c.o, c.c)), bottom = y(min(c.o, c.c))
            let body = CGRect(x: cx - bodyW / 2, y: top, width: bodyW, height: max(1, bottom - top))
            ctx.setFillColor(color.cgColor)
            ctx.fill(body)
            if i == n - 1 && forming != nil {           // формирующаяся свеча — с обводкой
                ctx.setStrokeColor(UIColor.white.withAlphaComponent(0.55).cgColor)
                ctx.setLineWidth(1)
                ctx.stroke(body.insetBy(dx: -1.5, dy: -1.5))
            }
            // объём
            let vh = CGFloat(c.v / maxV) * vr.height
            ctx.setFillColor(color.withAlphaComponent(0.35).cgColor)
            ctx.fill(CGRect(x: cx - bodyW / 2, y: vr.maxY - vh, width: bodyW, height: vh))
        }

        // прогнозная свеча LSTM
        if showPrediction, let p = prediction {
            let cx = x(for: n, count: n)
            let col = Theme.color(for: predictionAction)
            ctx.setStrokeColor(col.cgColor)
            ctx.setLineWidth(1.2)
            ctx.setLineDash(phase: 0, lengths: [3, 2])
            ctx.move(to: CGPoint(x: cx, y: y(p.high))); ctx.addLine(to: CGPoint(x: cx, y: y(p.low))); ctx.strokePath()
            let top = y(max(p.open, p.close)), bottom = y(min(p.open, p.close))
            let body = CGRect(x: cx - bodyW / 2, y: top, width: bodyW, height: max(2, bottom - top))
            ctx.setFillColor(col.withAlphaComponent(0.18).cgColor)
            ctx.fill(body)
            ctx.stroke(body)
            ctx.setLineDash(phase: 0, lengths: [])
            let tag = "LSTM" as NSString
            tag.draw(at: CGPoint(x: cx - 12, y: max(pr.minY, y(p.high) - 14)),
                     withAttributes: [.font: UIFont.systemFont(ofSize: 9, weight: .bold), .foregroundColor: col])
        }
        ctx.restoreGState()

        // линии открытых позиций
        for line in positionLines where line.price >= minP && line.price <= maxP {
            let yy = y(line.price)
            let col = line.isLong ? Theme.bull : Theme.bear
            ctx.setStrokeColor(col.withAlphaComponent(0.8).cgColor)
            ctx.setLineWidth(1)
            ctx.setLineDash(phase: 0, lengths: [6, 4])
            ctx.move(to: CGPoint(x: pr.minX, y: yy)); ctx.addLine(to: CGPoint(x: pr.maxX, y: yy)); ctx.strokePath()
            ctx.setLineDash(phase: 0, lengths: [])
            drawTag(line.label, at: CGPoint(x: pr.minX + 4, y: yy), color: col, ctx: ctx, leftAligned: true)
        }

        // линия текущей цены
        if let last = data.last {
            let yy = y(last.c)
            let col = last.isBullish ? Theme.bull : Theme.bear
            ctx.setStrokeColor(col.withAlphaComponent(0.7).cgColor)
            ctx.setLineWidth(1)
            ctx.setLineDash(phase: 0, lengths: [2, 3])
            ctx.move(to: CGPoint(x: pr.minX, y: yy)); ctx.addLine(to: CGPoint(x: pr.maxX, y: yy)); ctx.strokePath()
            ctx.setLineDash(phase: 0, lengths: [])
            drawTag(Fmt.price(last.c, digits: digits), at: CGPoint(x: pr.maxX + 2, y: yy), color: col, ctx: ctx, leftAligned: true)
        }

        // перекрестие
        if let ch = crosshair {
            let i = min(max(index(atX: ch.x, count: n), 0), n - 1)
            let cx = x(for: i, count: n)
            ctx.setStrokeColor(UIColor.white.withAlphaComponent(0.5).cgColor)
            ctx.setLineWidth(0.8)
            ctx.setLineDash(phase: 0, lengths: [4, 3])
            ctx.move(to: CGPoint(x: cx, y: pr.minY)); ctx.addLine(to: CGPoint(x: cx, y: vr.maxY)); ctx.strokePath()
            let cy = min(max(ch.y, pr.minY), pr.maxY)
            ctx.move(to: CGPoint(x: pr.minX, y: cy)); ctx.addLine(to: CGPoint(x: pr.maxX, y: cy)); ctx.strokePath()
            ctx.setLineDash(phase: 0, lengths: [])
            let price = maxP - Double((cy - pr.minY) / pr.height) * (maxP - minP)
            drawTag(Fmt.price(price, digits: digits), at: CGPoint(x: pr.maxX + 2, y: cy), color: Theme.surfaceHigh, ctx: ctx, leftAligned: true)
            drawInfoBox(for: data[i], ctx: ctx)
        }
    }

    private func drawTag(_ text: String, at p: CGPoint, color: UIColor, ctx: CGContext, leftAligned: Bool) {
        let attrs: [NSAttributedString.Key: Any] = [.font: Theme.mono(10, .semibold), .foregroundColor: UIColor.white]
        let s = text as NSString
        let size = s.size(withAttributes: attrs)
        let r = CGRect(x: p.x, y: p.y - size.height / 2 - 2, width: size.width + 8, height: size.height + 4)
        ctx.setFillColor(color.cgColor)
        ctx.addPath(UIBezierPath(roundedRect: r, cornerRadius: 3).cgPath)
        ctx.fillPath()
        s.draw(at: CGPoint(x: r.minX + 4, y: r.minY + 2), withAttributes: attrs)
    }

    private func drawInfoBox(for c: Candle, ctx: CGContext) {
        let change = (c.c / c.o - 1) * 100
        let lines = [
            Fmt.time(c.t, daily: daily),
            "O \(Fmt.price(c.o, digits: digits))   H \(Fmt.price(c.h, digits: digits))",
            "L \(Fmt.price(c.l, digits: digits))   C \(Fmt.price(c.c, digits: digits))",
            "Δ \(Fmt.percent(change, digits: 3, sign: true))   V \(Int(c.v))",
        ]
        let attrs: [NSAttributedString.Key: Any] = [.font: Theme.mono(10.5), .foregroundColor: Theme.textPrimary]
        let w = lines.map { ($0 as NSString).size(withAttributes: attrs).width }.max() ?? 100
        let r = CGRect(x: plotRect.minX + 6, y: plotRect.minY + 4, width: w + 16, height: CGFloat(lines.count) * 15 + 10)
        ctx.setFillColor(Theme.background.withAlphaComponent(0.88).cgColor)
        ctx.addPath(UIBezierPath(roundedRect: r, cornerRadius: 8).cgPath)
        ctx.fillPath()
        for (k, line) in lines.enumerated() {
            (line as NSString).draw(at: CGPoint(x: r.minX + 8, y: r.minY + 5 + CGFloat(k) * 15), withAttributes: attrs)
        }
    }

    private func drawCentered(_ text: String, in r: CGRect) {
        let attrs: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 14), .foregroundColor: Theme.textSecondary]
        let s = text as NSString
        let size = s.size(withAttributes: attrs)
        s.draw(at: CGPoint(x: r.midX - size.width / 2, y: r.midY - size.height / 2), withAttributes: attrs)
    }

    // MARK: - Жесты

    @objc private func onPinch(_ g: UIPinchGestureRecognizer) {
        if g.state == .began { pinchStartSpacing = spacing }
        spacing = min(max(pinchStartSpacing * g.scale, 3), 36)
        setNeedsDisplay()
    }

    @objc private func onPan(_ g: UIPanGestureRecognizer) {
        if g.state == .began { panStartOffset = offset }
        let dx = g.translation(in: self).x
        let maxOffset = max(0, CGFloat(series.count) - 10)
        offset = min(max(panStartOffset + dx / spacing, 0), maxOffset)
        setNeedsDisplay()
    }

    @objc private func onPress(_ g: UILongPressGestureRecognizer) {
        switch g.state {
        case .began, .changed: crosshair = g.location(in: self)
        default: crosshair = nil
        }
        setNeedsDisplay()
    }

    @objc private func onDoubleTap() {
        offset = 0
        spacing = 9
        setNeedsDisplay()
    }

    override func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
        guard let pan = g as? UIPanGestureRecognizer else { return true }
        let v = pan.velocity(in: self)
        return abs(v.x) > abs(v.y)          // вертикальный свайп отдаём UIScrollView
    }
}
