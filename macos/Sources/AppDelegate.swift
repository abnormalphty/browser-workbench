import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let backend = Backend()
    private var window: MainWindowController!
    private var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = buildMenu()
        window = MainWindowController()
        window.onRetry = { [weak self] in self?.backend.restart() }
        backend.onStateChange = { [weak self] state in self?.backendChanged(state) }
        window.showWindow(nil)
        window.showStatus("正在启动工作台…", detail: "首次打开会同时检查 Docker 和浏览器组件。")
        backend.start()
        // A self-test run stays in the background so it never takes over the keyboard.
        if AppPaths.environment["BROWSER_WORKBENCH_UI_TEST"] == nil { NSApp.activate(ignoringOtherApps: true) }
    }

    private func backendChanged(_ state: Backend.State) {
        guard !quitting else { return }
        switch state {
        case .ready(let port): window.load(port: port)
        case .failed(let message): window.showStatus("工作台没有启动", detail: message, isError: true)
        case .starting: window.showStatus("正在启动工作台…")
        case .stopped: break
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(nil)
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    @objc func showWindow(_ sender: Any?) {
        window.showWindow(nil)
        window.window?.makeKeyAndOrderFront(nil)
    }

    // MARK: Quitting

    /// Logout, restart and shutdown must not wait on a question nobody will answer.
    private var systemIsEndingSession: Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent,
              let reason = event.attributeDescriptor(forKeyword: AEKeyword(kAEQuitReason))?.enumCodeValue else { return false }
        return [kAELogOut, kAEReallyLogOut, kAEShowRestartDialog, kAERestart, kAEShowShutdownDialog, kAEShutDown].contains(reason)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return backend.port == nil ? .terminateNow : .terminateLater }
        guard backend.port != nil else {
            quitting = true
            backend.stop { NSApp.reply(toApplicationShouldTerminate: true) }
            return .terminateLater
        }
        let endingSession = systemIsEndingSession
        backend.summary { [weak self] summary in
            guard let self else { return }
            guard let summary, summary.active > 0 else { return self.finishQuit(stopEnvironments: false) }
            if endingSession { return self.finishQuit(stopEnvironments: true) }
            self.askBeforeQuitting(summary)
        }
        return .terminateLater
    }

    private func askBeforeQuitting(_ summary: Backend.Summary) {
        let alert = NSAlert()
        alert.messageText = "还有 \(summary.active) 个环境在运行"
        let names = summary.names.prefix(5).joined(separator: "、")
        alert.informativeText = (names.isEmpty ? "" : "\(names)。\n\n")
            + "“停止环境并退出”会正常关闭浏览器并保存登录数据，释放内存。\n“保留运行”时环境继续在 Docker 里占用内存，下次打开应用可以接着用。"
        alert.addButton(withTitle: "停止环境并退出")
        alert.addButton(withTitle: "保留运行并退出")
        alert.addButton(withTitle: "取消")
        showWindow(nil)
        switch alert.runModal() {
        case .alertFirstButtonReturn: finishQuit(stopEnvironments: true)
        case .alertSecondButtonReturn: finishQuit(stopEnvironments: false)
        default: NSApp.reply(toApplicationShouldTerminate: false)
        }
    }

    /// Used only by the developer self-test, which cannot click the quit dialog.
    func quitForTest(stopEnvironments: Bool) {
        finishQuitThenTerminate(stopEnvironments: stopEnvironments)
    }

    private func finishQuitThenTerminate(stopEnvironments: Bool) {
        quitting = true
        let shutdown: () -> Void = { [weak self] in
            self?.backend.stop { NSApp.terminate(nil) }
        }
        guard stopEnvironments else { return shutdown() }
        backend.stopAllEnvironments { _ in shutdown() }
    }

    private func finishQuit(stopEnvironments: Bool) {
        quitting = true
        let shutdown: () -> Void = { [weak self] in
            self?.backend.stop { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        guard stopEnvironments else { return shutdown() }
        window.showStatus("正在停止环境…", detail: "正在关闭浏览器并保存登录数据，通常需要几秒钟。")
        backend.stopAllEnvironments { _ in shutdown() }
    }

    // MARK: Menu actions

    @objc func showDataFolder(_ sender: Any?) {
        NSWorkspace.shared.activateFileViewerSelecting([AppPaths.dataDirectory])
    }

    @objc func showLogs(_ sender: Any?) {
        NSWorkspace.shared.activateFileViewerSelecting([AppPaths.backendLog])
    }

    @objc func reloadPage(_ sender: Any?) {
        if let port = backend.port { window.load(port: port) } else { backend.restart() }
    }

    @objc func restartBackend(_ sender: Any?) {
        backend.restart()
    }

    @objc func openHelp(_ sender: Any?) {
        NSWorkspace.shared.open(URL(string: "https://github.com/abnormalphty/browser-workbench#readme")!)
    }

    @objc func zoomIn(_ sender: Any?) { window.webView.pageZoom = min(window.webView.pageZoom + 0.1, 2) }
    @objc func zoomOut(_ sender: Any?) { window.webView.pageZoom = max(window.webView.pageZoom - 0.1, 0.6) }
    @objc func zoomReset(_ sender: Any?) { window.webView.pageZoom = 1 }

    @objc func importLegacyData(_ sender: Any?) {
        LegacyImport(backend: backend, window: window).begin()
    }

    // MARK: Menu bar

    private func buildMenu() -> NSMenu {
        let main = NSMenu()
        func submenu(_ title: String, _ items: [NSMenuItem]) {
            let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            holder.submenu = menu
            main.addItem(holder)
        }
        func item(_ title: String, _ action: Selector?, _ key: String = "", _ modifiers: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
            entry.keyEquivalentModifierMask = modifiers
            return entry
        }
        let hideOthers = item("隐藏其他", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option])
        submenu("境工作台", [
            item("关于境工作台", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("隐藏境工作台", #selector(NSApplication.hide(_:)), "h"),
            hideOthers,
            item("全部显示", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("退出境工作台", #selector(NSApplication.terminate(_:)), "q"),
        ])
        submenu("文件", [
            item("导入旧版工作台数据…", #selector(importLegacyData(_:))),
            .separator(),
            item("在 Finder 中显示数据文件夹", #selector(showDataFolder(_:))),
            item("显示日志", #selector(showLogs(_:))),
            .separator(),
            item("关闭窗口", #selector(NSWindow.performClose(_:)), "w"),
        ])
        // Without an Edit menu, ⌘C / ⌘V / ⌘A never reach text fields in the page.
        submenu("编辑", [
            item("撤销", Selector(("undo:")), "z"),
            item("重做", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("剪切", #selector(NSText.cut(_:)), "x"),
            item("拷贝", #selector(NSText.copy(_:)), "c"),
            item("粘贴", #selector(NSText.paste(_:)), "v"),
            item("全选", #selector(NSText.selectAll(_:)), "a"),
        ])
        submenu("显示", [
            item("重新载入工作台", #selector(reloadPage(_:)), "r", [.command, .shift]),
            item("重新启动后台服务", #selector(restartBackend(_:))),
            .separator(),
            item("放大", #selector(zoomIn(_:)), "+"),
            item("缩小", #selector(zoomOut(_:)), "-"),
            item("实际大小", #selector(zoomReset(_:)), "0"),
        ])
        let windowMenuItems = [
            item("最小化", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("缩放", #selector(NSWindow.performZoom(_:))),
            .separator(),
            item("境工作台", #selector(showWindow(_:)), "1"),
        ]
        submenu("窗口", windowMenuItems)
        NSApp.windowsMenu = main.items.last?.submenu
        submenu("帮助", [item("使用说明", #selector(openHelp(_:)))])
        return main
    }
}
