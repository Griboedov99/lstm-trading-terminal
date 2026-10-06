import UIKit

/// Главный экран: график свечей, рекомендация модели, ручная/автоматическая торговля, состояние счёта.
final class TerminalViewController: UIViewController, UITextFieldDelegate {

    private let store = TerminalStore.shared

    private let scroll = UIScrollView()
    private let stack = UIStackView()

    // шапка
    private let symbolButton = UIButton(type: .system)
    private let statusDot = UIView()
    private let statusLabel = UILabel()
    private let priceLabel = UILabel()
    private let changeLabel = UILabel()
    private let metaLabel = UILabel()

    // график и сигнал
    private let chart = CandleChartView()
    private let signalCard = SignalCardView()

    // торговля
    private let modeControl = UISegmentedControl(items: ["Ручная торговля", "Автоторговля"])
    private let qtyField = UITextField()
    private let qtyStepper = UIStepper()
    private let buyButton = UIButton(type: .system)
    private let sellButton = UIButton(type: .system)
    private let closeAllButton = UIButton(type: .system)
    private let modeHint = UILabel()
    private let botLogLabel = UILabel()

    // счёт
    private let balanceTile = StatTileView(title: "Баланс")
    private let equityTile = StatTileView(title: "Эквити")
    private let pnlTile = StatTileView(title: "P&L открытых")
    private let totalTile = StatTileView(title: "Итог P&L")
    private let positionsTile = StatTileView(title: "Позиции")
    private let winrateTile = StatTileView(title: "Winrate")

    private var qtyTouchedForSymbol: String?

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Терминал"
        view.backgroundColor = Theme.background
        buildLayout()
        NotificationCenter.default.addObserver(self, selector: #selector(storeChanged(_:)),
                                               name: .terminalStoreDidChange, object: nil)
        refreshAll()
    }

    // MARK: - Вёрстка

    private func buildLayout() {
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.alwaysBounceVertical = true
        scroll.keyboardDismissMode = .interactive
        view.addSubview(scroll)
        stack.axis = .vertical
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 8),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -24),
            stack.leadingAnchor.constraint(equalTo: scroll.frameLayoutGuide.leadingAnchor, constant: 12),
            stack.trailingAnchor.constraint(equalTo: scroll.frameLayoutGuide.trailingAnchor, constant: -12),
        ])

        stack.addArrangedSubview(makeHeader())
        chart.translatesAutoresizingMaskIntoConstraints = false
        chart.heightAnchor.constraint(equalToConstant: 340).isActive = true
        stack.addArrangedSubview(chart)
        let hint = UILabel()
        hint.text = "pinch — масштаб · свайп — история · удержание — OHLC · двойной тап — сброс"
        hint.font = .systemFont(ofSize: 10)
        hint.textColor = Theme.textSecondary
        hint.textAlignment = .center
        hint.adjustsFontSizeToFitWidth = true
        stack.addArrangedSubview(hint)
        stack.setCustomSpacing(6, after: chart)
        stack.addArrangedSubview(signalCard)
        stack.addArrangedSubview(makeTradingCard())
        stack.addArrangedSubview(makeAccountCard())
    }

    private func makeHeader() -> UIView {
        let card = CardView()
        symbolButton.titleLabel?.font = .systemFont(ofSize: 20, weight: .bold)
        symbolButton.setTitleColor(Theme.textPrimary, for: .normal)
        symbolButton.tintColor = Theme.textPrimary
        symbolButton.setImage(UIImage(systemName: "chevron.down"), for: .normal)
        symbolButton.semanticContentAttribute = .forceRightToLeft
        symbolButton.imageEdgeInsets = UIEdgeInsets(top: 0, left: 6, bottom: 0, right: -6)
        symbolButton.showsMenuAsPrimaryAction = true
        symbolButton.contentHorizontalAlignment = .leading

        statusDot.layer.cornerRadius = 4
        statusDot.translatesAutoresizingMaskIntoConstraints = false
        statusDot.widthAnchor.constraint(equalToConstant: 8).isActive = true
        statusDot.heightAnchor.constraint(equalToConstant: 8).isActive = true
        statusLabel.font = .systemFont(ofSize: 11, weight: .medium)
        statusLabel.textColor = Theme.textSecondary
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 180).isActive = true
        let status = UIStackView(arrangedSubviews: [statusDot, statusLabel])
        status.spacing = 5
        status.alignment = .center
        let top = UIStackView(arrangedSubviews: [symbolButton, UIView(), status])
        top.alignment = .center

        priceLabel.font = Theme.mono(28, .bold)
        priceLabel.textColor = Theme.textPrimary
        priceLabel.text = "—"
        changeLabel.font = Theme.mono(14, .semibold)
        let priceRow = UIStackView(arrangedSubviews: [priceLabel, changeLabel, UIView()])
        priceRow.spacing = 10
        priceRow.alignment = .lastBaseline

        metaLabel.font = .systemFont(ofSize: 11)
        metaLabel.textColor = Theme.textSecondary
        metaLabel.numberOfLines = 2

        let v = UIStackView(arrangedSubviews: [top, priceRow, metaLabel])
        v.axis = .vertical
        v.spacing = 4
        pin(v, into: card, inset: 14)
        return card
    }

    private func makeTradingCard() -> UIView {
        let card = CardView()
        modeControl.selectedSegmentIndex = 0
        modeControl.selectedSegmentTintColor = Theme.accent
        modeControl.setTitleTextAttributes([.foregroundColor: UIColor.white, .font: UIFont.systemFont(ofSize: 13, weight: .semibold)], for: .selected)
        modeControl.setTitleTextAttributes([.foregroundColor: Theme.textSecondary], for: .normal)
        modeControl.addTarget(self, action: #selector(modeChanged), for: .valueChanged)

        let qtyTitle = UILabel()
        qtyTitle.text = "Объём"
        qtyTitle.font = .systemFont(ofSize: 13, weight: .medium)
        qtyTitle.textColor = Theme.textSecondary
        qtyField.font = Theme.mono(16, .semibold)
        qtyField.textColor = Theme.textPrimary
        qtyField.keyboardType = .decimalPad
        qtyField.textAlignment = .right
        qtyField.backgroundColor = Theme.surfaceHigh
        qtyField.layer.cornerRadius = 8
        qtyField.delegate = self
        qtyField.leftView = UIView(frame: CGRect(x: 0, y: 0, width: 8, height: 1)); qtyField.leftViewMode = .always
        qtyField.rightView = UIView(frame: CGRect(x: 0, y: 0, width: 8, height: 1)); qtyField.rightViewMode = .always
        qtyField.translatesAutoresizingMaskIntoConstraints = false
        qtyField.widthAnchor.constraint(equalToConstant: 120).isActive = true
        qtyField.heightAnchor.constraint(equalToConstant: 36).isActive = true
        qtyField.addTarget(self, action: #selector(qtyEdited), for: .editingChanged)
        let toolbar = UIToolbar(frame: CGRect(x: 0, y: 0, width: 320, height: 44))
        toolbar.items = [UIBarButtonItem(barButtonSystemItem: .flexibleSpace, target: nil, action: nil),
                         UIBarButtonItem(title: "Готово", style: .done, target: self, action: #selector(doneEditing))]
        qtyField.inputAccessoryView = toolbar
        qtyStepper.addTarget(self, action: #selector(stepperChanged), for: .valueChanged)
        qtyStepper.tintColor = Theme.textPrimary
        qtyStepper.backgroundColor = Theme.surfaceHigh
        qtyStepper.layer.cornerRadius = 8
        let qtyRow = UIStackView(arrangedSubviews: [qtyTitle, UIView(), qtyField, qtyStepper])
        qtyRow.spacing = 8
        qtyRow.alignment = .center

        style(sellButton, title: "SELL", color: Theme.bear)
        style(buyButton, title: "BUY", color: Theme.bull)
        sellButton.addTarget(self, action: #selector(sellTapped), for: .touchUpInside)
        buyButton.addTarget(self, action: #selector(buyTapped), for: .touchUpInside)
        let buttons = UIStackView(arrangedSubviews: [sellButton, buyButton])
        buttons.spacing = 10
        buttons.distribution = .fillEqually

        closeAllButton.setTitle("Закрыть все позиции", for: .normal)
        closeAllButton.setTitleColor(Theme.textPrimary, for: .normal)
        closeAllButton.titleLabel?.font = .systemFont(ofSize: 14, weight: .semibold)
        closeAllButton.backgroundColor = Theme.surfaceHigh
        closeAllButton.layer.cornerRadius = 10
        closeAllButton.heightAnchor.constraint(equalToConstant: 40).isActive = true
        closeAllButton.addTarget(self, action: #selector(closeAllTapped), for: .touchUpInside)

        modeHint.font = .systemFont(ofSize: 12)
        modeHint.textColor = Theme.textSecondary
        modeHint.numberOfLines = 0
        botLogLabel.font = Theme.mono(11)
        botLogLabel.textColor = Theme.textPrimary
        botLogLabel.numberOfLines = 0

        let v = UIStackView(arrangedSubviews: [modeControl, modeHint, qtyRow, buttons, closeAllButton, botLogLabel])
        v.axis = .vertical
        v.spacing = 12
        pin(v, into: card, inset: 14)
        return card
    }

    private func makeAccountCard() -> UIView {
        let card = CardView()
        let row1 = UIStackView(arrangedSubviews: [balanceTile, equityTile, pnlTile])
        let row2 = UIStackView(arrangedSubviews: [totalTile, positionsTile, winrateTile])
        for r in [row1, row2] { r.distribution = .fillEqually; r.spacing = 10 }
        let title = UILabel()
        title.text = "ДЕМО-СЧЁТ"
        title.font = .systemFont(ofSize: 11, weight: .semibold)
        title.textColor = Theme.textSecondary
        let v = UIStackView(arrangedSubviews: [title, row1, row2])
        v.axis = .vertical
        v.spacing = 12
        pin(v, into: card, inset: 14)
        return card
    }

    private func style(_ b: UIButton, title: String, color: UIColor) {
        b.setTitle(title, for: .normal)
        b.setTitleColor(.white, for: .normal)
        b.setTitleColor(UIColor.white.withAlphaComponent(0.5), for: .disabled)
        b.titleLabel?.font = .systemFont(ofSize: 18, weight: .heavy)
        b.backgroundColor = color
        b.layer.cornerRadius = 12
        b.heightAnchor.constraint(equalToConstant: 52).isActive = true
    }

    private func pin(_ v: UIView, into card: UIView, inset: CGFloat) {
        v.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(v)
        NSLayoutConstraint.activate([
            v.topAnchor.constraint(equalTo: card.topAnchor, constant: inset),
            v.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -inset),
            v.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: inset),
            v.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -inset),
        ])
    }

    // MARK: - Обновление UI

    @objc private func storeChanged(_ n: Notification) {
        guard let kind = n.userInfo?["kind"] as? TerminalStore.Change else { return }
        switch kind {
        case .tick:
            updateChart(); updatePrice(); updateAccount()
        case .connection:
            updateStatus()
        case .symbols:
            updateSymbolMenu()
        case .snapshot, .candle, .account:
            refreshAll()
        }
    }

    private func refreshAll() {
        updateStatus(); updateSymbolMenu(); updateChart(); updatePrice()
        signalCard.update(signal: store.signal, digits: store.digits, lastClose: store.candles.last?.c)
        updateTrading(); updateAccount()
    }

    private func updateStatus() {
        let state: (text: String, color: UIColor)
        switch store.connection {
        case .connected: state = ("онлайн", Theme.bull)
        case .connecting: state = ("подключение…", Theme.hold)
        case .disconnected: state = ("нет связи", Theme.textSecondary)
        case .failed(let e): state = ("переподключение: \(e)", Theme.bear)
        }
        statusLabel.text = state.text
        statusDot.backgroundColor = state.color
    }

    private func updateSymbolMenu() {
        symbolButton.setTitle(store.symbol + " ", for: .normal)
        let list = store.symbols.isEmpty ? [store.symbol] : store.symbols.map(\.symbol)
        let titles = Dictionary(uniqueKeysWithValues: store.symbols.map { ($0.symbol, $0.title) })
        let actions = list.map { sym in
            UIAction(title: sym, subtitle: titles[sym], state: sym == store.symbol ? .on : .off) { [weak self] _ in
                self?.qtyTouchedForSymbol = nil
                self?.store.select(symbol: sym)
            }
        }
        symbolButton.menu = UIMenu(title: "Инструмент", children: actions)
    }

    private func updateChart() {
        let lines = (store.account?.positions ?? []).map {
            CandleChartView.PositionLine(price: $0.entryPrice, isLong: $0.isLong,
                                         label: "\($0.isLong ? "L" : "S") \(Fmt.qty($0.qty)) \(Fmt.money($0.pnl, sign: true))")
        }
        chart.update(candles: store.candles, forming: store.forming, prediction: store.signal?.predicted,
                     action: store.signal?.kind ?? .hold, positions: lines, digits: store.digits,
                     daily: (store.info?.timeframe ?? "H1") == "D1")
    }

    private func updatePrice() {
        guard let price = store.lastPrice else { priceLabel.text = "—"; changeLabel.text = nil; return }
        priceLabel.text = Fmt.price(price, digits: store.digits)
        let prevClose: Double? = store.forming != nil ? store.candles.last?.c
            : (store.candles.count > 1 ? store.candles[store.candles.count - 2].c : nil)
        if let prev = prevClose, prev > 0 {
            let ch = (price / prev - 1) * 100
            changeLabel.text = Fmt.percent(ch, digits: 3, sign: true)
            changeLabel.textColor = Theme.pnlColor(ch)
        }
        if let info = store.info {
            let src = ["replay": "воспроизведение истории (тест)", "synthetic": "синтетика GBM",
                       "binance": "Binance live"][info.source] ?? info.source
            let last = store.candles.last.map { Fmt.time($0.t, daily: info.timeframe == "D1") } ?? "—"
            metaLabel.text = "\(info.title) · \(info.timeframe) · \(src)\nмодель \(info.model.name): LSTM \(info.model.layers)×\(info.model.hidden), окно \(info.model.lookback) · свеча \(last)"
        }
    }

    private func updateTrading() {
        let auto = store.isAuto
        modeControl.selectedSegmentIndex = auto ? 1 : 0
        buyButton.isEnabled = !auto
        sellButton.isEnabled = !auto
        buyButton.alpha = auto ? 0.4 : 1
        sellButton.alpha = auto ? 0.4 : 1
        modeHint.text = auto
            ? "Бот исполняет рекомендации на закрытии каждой свечи: BUY → long, SELL → short, HOLD → вне рынка. Объём ниже — размер позиции бота."
            : "Вы открываете и закрываете сделки сами; рекомендация модели — подсказка."
        if qtyTouchedForSymbol != store.symbol, let info = store.info {
            let q = auto && store.autoQty > 0 ? store.autoQty : info.defaultQty
            qtyField.text = Fmt.qty(q).replacingOccurrences(of: "K", with: "000")
            qtyStepper.minimumValue = info.defaultQty / 10
            qtyStepper.maximumValue = info.defaultQty * 100
            qtyStepper.stepValue = info.defaultQty
            qtyStepper.value = q
        }
        let log = store.botLog.suffix(4).reversed().map { "• \($0.message)" }
        botLogLabel.text = log.isEmpty ? nil : "Журнал бота:\n" + log.joined(separator: "\n")
        botLogLabel.isHidden = log.isEmpty
    }

    private func updateAccount() {
        guard let a = store.account else { return }
        balanceTile.set(Fmt.money(a.balance))
        equityTile.set(Fmt.money(a.equity))
        pnlTile.set(Fmt.money(a.unrealizedPnl, sign: true), color: Theme.pnlColor(a.unrealizedPnl))
        let total = a.equity - a.initialBalance
        totalTile.set(Fmt.money(total, sign: true), color: Theme.pnlColor(total))
        let net = a.positions.reduce(0.0) { $0 + ($1.isLong ? $1.qty : -$1.qty) }
        positionsTile.set(a.positions.isEmpty ? "нет" : "\(a.positions.count) · нетто \(net >= 0 ? "+" : "−")\(Fmt.qty(abs(net)))")
        winrateTile.set(a.stats.trades > 0 ? "\(Fmt.percent(a.stats.winrate * 100, digits: 0)) / \(a.stats.trades)" : "—")
    }

    // MARK: - Действия

    private var qty: Double {
        Double((qtyField.text ?? "").replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: " ", with: "")) ?? 0
    }

    @objc private func modeChanged() {
        let auto = modeControl.selectedSegmentIndex == 1
        store.setMode(auto: auto, qty: qty > 0 ? qty : (store.info?.defaultQty ?? 1)) { [weak self] err in
            if let err = err { self?.showError(err); self?.updateTrading() }
        }
        UISelectionFeedbackGenerator().selectionChanged()
    }

    @objc private func buyTapped() { send(side: "buy") }
    @objc private func sellTapped() { send(side: "sell") }

    private func send(side: String) {
        guard qty > 0 else { return }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        store.order(side: side, qty: qty) { [weak self] err in
            if let err = err { self?.showError(err) }
        }
    }

    @objc private func closeAllTapped() {
        store.closeAll { [weak self] err in if let err = err { self?.showError(err) } }
    }

    @objc private func qtyEdited() {
        qtyTouchedForSymbol = store.symbol
        qtyStepper.value = qty
    }

    @objc private func stepperChanged() {
        qtyTouchedForSymbol = store.symbol
        qtyField.text = Fmt.qty(qtyStepper.value).replacingOccurrences(of: "K", with: "000")
    }

    @objc private func doneEditing() {
        view.endEditing(true)
        if store.isAuto { modeChanged() }      // в автоторговле объём сразу уходит боту
    }
}
