import UIKit

/// Адрес сервера, скорость эмуляции, сброс демо-счёта.
final class SettingsViewController: UIViewController, UITextFieldDelegate {

    private let store = TerminalStore.shared
    private let urlField = UITextField()
    private let speedSlider = UISlider()
    private let speedLabel = UILabel()

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Настройки"
        view.backgroundColor = Theme.background

        urlField.text = APIClient.shared.baseURL.absoluteString
        urlField.placeholder = APIClient.defaultURL
        urlField.font = Theme.mono(15)
        urlField.textColor = Theme.textPrimary
        urlField.backgroundColor = Theme.surfaceHigh
        urlField.layer.cornerRadius = 8
        urlField.autocapitalizationType = .none
        urlField.autocorrectionType = .no
        urlField.keyboardType = .URL
        urlField.returnKeyType = .done
        urlField.delegate = self
        urlField.leftView = UIView(frame: CGRect(x: 0, y: 0, width: 10, height: 1)); urlField.leftViewMode = .always
        urlField.heightAnchor.constraint(equalToConstant: 42).isActive = true

        let connect = makeButton("Подключиться", color: Theme.accent, action: #selector(connectTapped))

        speedSlider.minimumValue = 0.3
        speedSlider.maximumValue = 10
        speedSlider.value = Float(store.info?.candleSeconds ?? 2)
        speedSlider.tintColor = Theme.accent
        speedSlider.addTarget(self, action: #selector(speedMoved), for: .valueChanged)
        speedSlider.addTarget(self, action: #selector(speedCommitted), for: [.touchUpInside, .touchUpOutside])
        speedLabel.font = Theme.mono(13)
        speedLabel.textColor = Theme.textPrimary
        speedMoved()

        let reset = makeButton("Сбросить демо-счёт", color: Theme.bear, action: #selector(resetTapped))

        let about = UILabel()
        about.numberOfLines = 0
        about.font = .systemFont(ofSize: 12)
        about.textColor = Theme.textSecondary
        about.text = """
        Сервер: docker compose up → http://<IP компьютера>:8000.
        В симуляторе подходит http://localhost:8000; на iPhone укажите IP Mac в локальной сети.

        Рекомендации строит LSTM по масштабно-инвариантным признакам (лог-приращения, RSI, MACD, волатильность), \
        поэтому прогноз не зависит от абсолютного уровня цены.
        """

        let stack = UIStackView(arrangedSubviews: [
            section("Сервер", [urlField, connect]),
            section("Скорость эмуляции (текущий инструмент)", [speedLabel, speedSlider]),
            section("Демо-счёт", [reset]),
            about,
        ])
        stack.axis = .vertical
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 16),
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
        ])
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        if let s = store.info?.candleSeconds { speedSlider.value = Float(s); speedMoved() }
    }

    private func section(_ title: String, _ views: [UIView]) -> UIView {
        let l = UILabel()
        l.text = title.uppercased()
        l.font = .systemFont(ofSize: 11, weight: .semibold)
        l.textColor = Theme.textSecondary
        let s = UIStackView(arrangedSubviews: [l] + views)
        s.axis = .vertical
        s.spacing = 8
        return s
    }

    private func makeButton(_ title: String, color: UIColor, action: Selector) -> UIButton {
        let b = UIButton(type: .system)
        b.setTitle(title, for: .normal)
        b.setTitleColor(.white, for: .normal)
        b.titleLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        b.backgroundColor = color
        b.layer.cornerRadius = 10
        b.heightAnchor.constraint(equalToConstant: 44).isActive = true
        b.addTarget(self, action: action, for: .touchUpInside)
        return b
    }

    @objc private func connectTapped() {
        view.endEditing(true)
        guard let text = urlField.text, URL(string: text)?.host != nil else {
            showError(APIClient.APIError.server("Неверный адрес, пример: http://192.168.1.10:8000"))
            return
        }
        APIClient.shared.setBaseURL(text)
        store.reconnect()
        tabBarController?.selectedIndex = 0
    }

    @objc private func speedMoved() {
        let v = Double(speedSlider.value)
        speedLabel.text = String(format: "1 свеча = %.1f с  (≈ %.0f свечей/мин)", v, 60 / v)
    }

    @objc private func speedCommitted() {
        store.setSpeed(Double(speedSlider.value)) { [weak self] err in if let err = err { self?.showError(err) } }
    }

    @objc private func resetTapped() {
        let a = UIAlertController(title: "Сбросить счёт?", message: "Позиции и история по \(store.symbol) будут удалены, режим — ручной.",
                                  preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Отмена", style: .cancel))
        a.addAction(UIAlertAction(title: "Сбросить", style: .destructive) { [weak self] _ in
            self?.store.resetAccount { err in if let err = err { self?.showError(err) } }
        })
        present(a, animated: true)
    }

    func textFieldShouldReturn(_ textField: UITextField) -> Bool {
        connectTapped()
        return true
    }
}
