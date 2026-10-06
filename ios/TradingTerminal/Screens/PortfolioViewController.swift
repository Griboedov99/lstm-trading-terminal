import UIKit

/// Открытые позиции, история сделок, журнал бота, кривая капитала и статистика.
final class PortfolioViewController: UITableViewController {

    private let store = TerminalStore.shared
    private let equityChart = EquityChartView()
    private let statsLabel = UILabel()

    private enum Section: Int, CaseIterable { case open, history, bot }

    init() { super.init(style: .insetGrouped) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Портфель"
        tableView.backgroundColor = Theme.background
        tableView.separatorColor = Theme.grid
        tableView.tableHeaderView = makeHeader()
        navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Закрыть всё", style: .plain,
                                                            target: self, action: #selector(closeAll))
        NotificationCenter.default.addObserver(self, selector: #selector(storeChanged(_:)),
                                               name: .terminalStoreDidChange, object: nil)
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        reload()
    }

    private func makeHeader() -> UIView {
        let header = UIView(frame: CGRect(x: 0, y: 0, width: view.bounds.width, height: 210))
        let card = CardView()
        card.translatesAutoresizingMaskIntoConstraints = false
        header.addSubview(card)
        statsLabel.font = Theme.mono(12)
        statsLabel.textColor = Theme.textPrimary
        statsLabel.numberOfLines = 0
        equityChart.translatesAutoresizingMaskIntoConstraints = false
        statsLabel.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(equityChart)
        card.addSubview(statsLabel)
        NSLayoutConstraint.activate([
            card.topAnchor.constraint(equalTo: header.topAnchor, constant: 8),
            card.bottomAnchor.constraint(equalTo: header.bottomAnchor, constant: -4),
            card.leadingAnchor.constraint(equalTo: header.leadingAnchor, constant: 16),
            card.trailingAnchor.constraint(equalTo: header.trailingAnchor, constant: -16),
            statsLabel.topAnchor.constraint(equalTo: card.topAnchor, constant: 12),
            statsLabel.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 12),
            statsLabel.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -12),
            equityChart.topAnchor.constraint(equalTo: statsLabel.bottomAnchor, constant: 6),
            equityChart.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 6),
            equityChart.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -6),
            equityChart.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -6),
        ])
        header.autoresizingMask = [.flexibleWidth]
        return header
    }

    @objc private func storeChanged(_ n: Notification) {
        guard isViewLoaded, view.window != nil else { return }
        let kind = n.userInfo?["kind"] as? TerminalStore.Change
        if kind == .tick {
            // на тиках обновляем только P&L видимых открытых позиций, без полной перезагрузки
            updateHeader()
            for ip in tableView.indexPathsForVisibleRows ?? [] where ip.section == Section.open.rawValue {
                if let cell = tableView.cellForRow(at: ip) { configureOpen(cell, row: ip.row) }
            }
        } else {
            reload()
        }
    }

    private func reload() {
        updateHeader()
        tableView.reloadData()
    }

    private func updateHeader() {
        guard let a = store.account else {
            statsLabel.text = "Нет данных — проверьте подключение к серверу"
            equityChart.update(points: [], baseline: 0)
            return
        }
        let s = a.stats
        statsLabel.text = """
        \(store.symbol) · режим: \(store.isAuto ? "автоторговля" : "ручной")
        Эквити \(Fmt.money(a.equity))   Итог \(Fmt.money(s.totalPnl, sign: true)) (\(Fmt.percent(s.returnPct, digits: 2, sign: true)))
        Сделок \(s.trades) · winrate \(Fmt.percent(s.winrate * 100, digits: 0)) · макс. просадка \(Fmt.percent(s.maxDrawdownPct, digits: 2))
        """
        var pts = a.equityCurve.map(\.equity)
        pts.append(a.equity)
        equityChart.update(points: pts, baseline: a.initialBalance)
    }

    // MARK: - Таблица

    override func numberOfSections(in tableView: UITableView) -> Int { Section.allCases.count }

    override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        switch Section(rawValue: section)! {
        case .open: return "Открытые позиции (\(store.account?.positions.count ?? 0))"
        case .history: return "История сделок (\(store.account?.history.count ?? 0))"
        case .bot: return "Журнал бота"
        }
    }

    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        let a = store.account
        switch Section(rawValue: section)! {
        case .open: return max(1, a?.positions.count ?? 0)
        case .history: return max(1, a?.history.count ?? 0)
        case .bot: return max(1, store.botLog.count)
        }
    }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.backgroundColor = Theme.surface
        cell.textLabel?.textColor = Theme.textPrimary
        cell.textLabel?.font = Theme.mono(14, .semibold)
        cell.detailTextLabel?.textColor = Theme.textSecondary
        cell.detailTextLabel?.font = Theme.mono(11)
        cell.detailTextLabel?.numberOfLines = 2
        cell.selectionStyle = .none
        let a = store.account
        let daily = store.info?.timeframe == "D1"
        switch Section(rawValue: indexPath.section)! {
        case .open:
            if (a?.positions.isEmpty ?? true) { empty(cell, "Нет открытых позиций") } else { configureOpen(cell, row: indexPath.row) }
        case .history:
            guard let t = a?.history[safe: indexPath.row] else { empty(cell, "Сделок пока нет"); break }
            cell.textLabel?.text = "\(t.side == "long" ? "▲ LONG" : "▼ SHORT") \(Fmt.qty(t.qty))  #\(t.id)"
            cell.textLabel?.textColor = t.side == "long" ? Theme.bull : Theme.bear
            cell.detailTextLabel?.text = "\(Fmt.price(t.entryPrice, digits: store.digits)) → \(Fmt.price(t.exitPrice, digits: store.digits))\n" +
                "\(Fmt.time(t.entryTime, daily: daily)) → \(Fmt.time(t.exitTime, daily: daily)) · \(t.openedBy == "bot" ? "бот" : "вручную")"
            cell.accessoryView = pnlLabel(t.pnl)
        case .bot:
            guard let e = Array(store.botLog.reversed())[safe: indexPath.row] else { empty(cell, "Бот ещё не торговал"); break }
            cell.textLabel?.text = e.message
            cell.textLabel?.font = .systemFont(ofSize: 13)
            cell.textLabel?.numberOfLines = 0
            cell.detailTextLabel?.text = Fmt.time(e.t, daily: daily)
        }
        return cell
    }

    private func configureOpen(_ cell: UITableViewCell, row: Int) {
        guard let p = store.account?.positions[safe: row] else { return }
        cell.textLabel?.text = "\(p.isLong ? "▲ LONG" : "▼ SHORT") \(Fmt.qty(p.qty))  #\(p.id)"
        cell.textLabel?.textColor = p.isLong ? Theme.bull : Theme.bear
        let cur = p.currentPrice ?? store.lastPrice ?? p.entryPrice
        cell.detailTextLabel?.text = "вход \(Fmt.price(p.entryPrice, digits: store.digits)) · сейчас \(Fmt.price(cur, digits: store.digits))\n" +
            "\(p.openedBy == "bot" ? "открыл бот" : "открыта вручную") · смахните влево, чтобы закрыть"
        cell.accessoryView = pnlLabel(p.pnl)
    }

    private func empty(_ cell: UITableViewCell, _ text: String) {
        cell.textLabel?.text = text
        cell.textLabel?.font = .systemFont(ofSize: 14)
        cell.textLabel?.textColor = Theme.textSecondary
    }

    private func pnlLabel(_ v: Double) -> UILabel {
        let l = UILabel()
        l.font = Theme.mono(14, .bold)
        l.textColor = Theme.pnlColor(v)
        l.text = Fmt.money(v, sign: true)
        l.sizeToFit()
        return l
    }

    override func tableView(_ tableView: UITableView,
                            trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath) -> UISwipeActionsConfiguration? {
        guard indexPath.section == Section.open.rawValue,
              let p = store.account?.positions[safe: indexPath.row] else { return nil }
        let close = UIContextualAction(style: .destructive, title: "Закрыть") { [weak self] _, _, done in
            self?.store.close(positionId: p.id) { err in
                if let err = err { self?.showError(err) }
                done(err == nil)
            }
        }
        return UISwipeActionsConfiguration(actions: [close])
    }

    @objc private func closeAll() {
        store.closeAll { [weak self] err in if let err = err { self?.showError(err) } }
    }
}

extension Collection {
    subscript(safe i: Index) -> Element? { indices.contains(i) ? self[i] : nil }
}
