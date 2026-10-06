import UIKit

final class MainTabBarController: UITabBarController {
    override func viewDidLoad() {
        super.viewDidLoad()
        let tabs: [(UIViewController, String, String)] = [
            (TerminalViewController(), "Терминал", "chart.bar.xaxis"),
            (PortfolioViewController(), "Портфель", "briefcase"),
            (ModelViewController(), "Модель", "brain"),
            (SettingsViewController(), "Настройки", "gearshape"),
        ]
        viewControllers = tabs.map { item -> UIViewController in
            let (vc, title, icon) = item
            let nav = UINavigationController(rootViewController: vc)
            nav.tabBarItem = UITabBarItem(title: title, image: UIImage(systemName: icon), selectedImage: nil)
            let appearance = UINavigationBarAppearance()
            appearance.configureWithOpaqueBackground()
            appearance.backgroundColor = Theme.background
            appearance.shadowColor = .clear
            appearance.titleTextAttributes = [.foregroundColor: Theme.textPrimary]
            appearance.largeTitleTextAttributes = [.foregroundColor: Theme.textPrimary]
            nav.navigationBar.standardAppearance = appearance
            nav.navigationBar.scrollEdgeAppearance = appearance
            return nav
        }
        let tabAppearance = UITabBarAppearance()
        tabAppearance.configureWithOpaqueBackground()
        tabAppearance.backgroundColor = Theme.surface
        tabBar.standardAppearance = tabAppearance
        tabBar.scrollEdgeAppearance = tabAppearance
        tabBar.tintColor = Theme.accent
    }
}
