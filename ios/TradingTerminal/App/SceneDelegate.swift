import UIKit

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        window.overrideUserInterfaceStyle = .dark
        window.tintColor = Theme.accent
        window.rootViewController = MainTabBarController()
        window.makeKeyAndVisible()
        self.window = window
        TerminalStore.shared.connect()
    }

    func sceneWillEnterForeground(_ scene: UIScene) {
        // после сна iOS разрывает сокет — переподключаемся и получаем свежий снимок
        switch TerminalStore.shared.connection {
        case .connected, .connecting: break
        default: TerminalStore.shared.connect()
        }
    }
}
