import UIKit

/// Качество модели и результаты бэктеста (GET /api/report).
final class ModelViewController: UITableViewController {

    private struct Row { let title: String; let value: String; var color: UIColor = Theme.textPrimary }
    private struct Block { let title: String; let footer: String?; let rows: [Row] }
    private var blocks: [Block] = []

    init() { super.init(style: .insetGrouped) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Модель"
        tableView.backgroundColor = Theme.background
        tableView.separatorColor = Theme.grid
        refreshControl = UIRefreshControl()
        refreshControl?.addTarget(self, action: #selector(load), for: .valueChanged)
        load()
    }

    @objc private func load() {
        APIClient.shared.report { [weak self] result in
            guard let self = self else { return }
            self.refreshControl?.endRefreshing()
            switch result {
            case .success(let json): self.blocks = self.parse(json)
            case .failure(let e): self.blocks = [Block(title: "Нет данных", footer: e.localizedDescription, rows: [])]
            }
            self.tableView.reloadData()
        }
    }

    private func num(_ any: Any?) -> Double { (any as? NSNumber)?.doubleValue ?? .nan }
    private func inum(_ any: Any?) -> Int { (any as? NSNumber)?.intValue ?? 0 }

    private func parse(_ json: [String: Any]) -> [Block] {
        var out: [Block] = []
        for key in ["eurusd_h1", "stocks_d1"] {
            guard let r = json[key] as? [String: Any] else { continue }
            let tf = r["timeframe"] as? String ?? ""
            let syms = (r["symbols"] as? [String] ?? []).joined(separator: ", ")
            let sel = r["selected"] as? [String: Any] ?? [:]
            let period = (r["test_period"] as? [String] ?? []).map { String($0.prefix(10)) }.joined(separator: " → ")
            out.append(Block(title: "\(key.uppercased()) · \(tf)", footer: "Тест: \(period). Тикеры: \(syms)", rows: [
                Row(title: "Архитектура", value: "LSTM \(inum(sel["layers"]))×\(inum(sel["hidden"]))"),
                Row(title: "Окно (lookback)", value: "\(inum(sel["lookback"])) свечей"),
            ]))

            if let m = r["metrics_test"] as? [String: [String: Any]] {
                let order = ["LSTM", "GRU", "ARIMA(1,0,1) on log-returns", "Naive (C_t+1 = C_t)", "LSTM on raw prices (min-max)"]
                let rows = order.compactMap { name -> Row? in
                    guard let v = m[name] else { return nil }
                    return Row(title: name, value: String(format: "MAPE %.3f%% · dir %.1f%%", num(v["MAPE_%"]), num(v["DirAcc_%"])))
                }
                out.append(Block(title: "Прогноз следующего close (тест)", footer:
                    "dir — доля верно угаданных направлений. LSTM на сырых ценах ломается, когда цена выходит за диапазон обучения.", rows: rows))
            }
            if let b = r["backtest"] as? [String: Any] {
                func rows(_ d: [String: Any]?) -> [Row] {
                    guard let d = d else { return [] }
                    let ret = num(d["total_return"]) * 100
                    return [
                        Row(title: "Доходность", value: Fmt.percent(ret, digits: 2, sign: true), color: Theme.pnlColor(ret)),
                        Row(title: "Sharpe (год.)", value: String(format: "%.2f", num(d["sharpe"]))),
                        Row(title: "Макс. просадка", value: Fmt.percent(num(d["max_drawdown"]) * 100, digits: 2)),
                        Row(title: "Winrate / сделок", value: "\(Fmt.percent(num(d["winrate"]) * 100, digits: 0)) / \(inum(d["n_trades"]))"),
                    ]
                }
                let th = b["thresholds"] as? [String: Any] ?? [:]
                out.append(Block(title: "Бэктест LSTM (тест, с издержками)",
                                 footer: String(format: "Порог P(up) = %.2f подобран на валидации. Издержки %.1f б.п. на оборот.",
                                                num(th["p_thr"]), num(b["cost_per_turnover"]) * 1e4),
                                 rows: rows(b["test"] as? [String: Any])))
                out.append(Block(title: "Buy & Hold (тот же период)", footer: nil, rows: rows(b["buy_and_hold"] as? [String: Any])))
            }
        }
        return out
    }

    override func numberOfSections(in tableView: UITableView) -> Int { blocks.count }
    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { blocks[section].rows.count }
    override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? { blocks[section].title }
    override func tableView(_ tableView: UITableView, titleForFooterInSection section: Int) -> String? { blocks[section].footer }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let row = blocks[indexPath.section].rows[indexPath.row]
        let cell = UITableViewCell(style: .value1, reuseIdentifier: nil)
        cell.backgroundColor = Theme.surface
        cell.selectionStyle = .none
        cell.textLabel?.text = row.title
        cell.textLabel?.textColor = Theme.textPrimary
        cell.textLabel?.font = .systemFont(ofSize: 13)
        cell.textLabel?.numberOfLines = 2
        cell.detailTextLabel?.text = row.value
        cell.detailTextLabel?.textColor = row.color
        cell.detailTextLabel?.font = Theme.mono(12, .semibold)
        return cell
    }
}
