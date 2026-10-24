import AppKit
import WebKit

/// WKUserContentController retains handlers strongly; this breaks the cycle.
private final class WeakScriptHandler: NSObject, WKScriptMessageHandlerWithReply {
    weak var target: WKScriptMessageHandlerWithReply?
    init(_ target: WKScriptMessageHandlerWithReply) { self.target = target }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        guard let target else { return replyHandler(nil, "unavailable") }
        target.userContentController(controller, didReceive: message, replyHandler: replyHandler)
    }
}

/// The single app window. Shows the local workbench page, or a native status page
/// while the backend starts or after it stops.
final class MainWindowController: NSWindowController, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate,
                                  WKDownloadDelegate, WKScriptMessageHandlerWithReply {
    let webView: WKWebView
    var onRetry: (() -> Void)?
    private var port: Int?
    private var downloads: [ObjectIdentifier: URL] = [:]
    /// Only files this window saved may be revealed on request from the page.
    private var revealable = Set<String>()

    init() {
        let configuration = WKWebViewConfiguration()
        let content = WKUserContentController()
        configuration.userContentController = content
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        webView = WKWebView(frame: .zero, configuration: configuration)

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "境工作台"
        window.minSize = NSSize(width: 960, height: 620)
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.contentView = webView
        if !window.setFrameUsingName("MainWindow") { window.center() }
        window.setFrameAutosaveName("MainWindow")
        super.init(window: window)
        window.delegate = self

        content.addScriptMessageHandler(WeakScriptHandler(self), contentWorld: .page, name: "workbench")
        content.addUserScript(WKUserScript(
            source: "window.workbenchNative={version:\(jsString(AppPaths.version))};",
            injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView.navigationDelegate = self
        webView.uiDelegate = self
        if #available(macOS 13.3, *) {
            webView.isInspectable = UserDefaults.standard.bool(forKey: "WebInspector")
        }
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    // MARK: Pages

    func load(port: Int) {
        self.port = port
        webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(port)/")!))
    }

    func showStatus(_ message: String, detail: String = "", isError: Bool = false) {
        port = nil
        webView.loadHTMLString(StatusPage.html(message: message, detail: detail, isError: isError), baseURL: nil)
    }

    /// Runs page JavaScript only while our own workbench page is showing.
    func notifyPage(event: String, detail: [String: Any]) {
        guard port != nil, let data = try? JSONSerialization.data(withJSONObject: detail),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent(\(jsString(event)),{detail:\(json)}))")
    }

    private func isWorkbench(_ url: URL?) -> Bool {
        guard let url, let port else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == port
    }

    // MARK: Navigation

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "workbench-native" {
            switch url.host {
            case "retry": onRetry?()
            case "logs": NSWorkspace.shared.activateFileViewerSelecting([AppPaths.backendLog])
            default: break
            }
            return decisionHandler(.cancel)
        }
        if action.shouldPerformDownload && isWorkbench(url) { return decisionHandler(.download) }
        if isWorkbench(url) || url.absoluteString == "about:blank" || url.absoluteString == "about:srcdoc" {
            return decisionHandler(.allow)
        }
        // Web links open in the user's browser; dropped files (file://) never replace the page.
        if (url.scheme == "http" || url.scheme == "https") && action.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        if disposition.lowercased().hasPrefix("attachment") || !response.canShowMIMEType {
            return decisionHandler(.download)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if port != nil && (error as NSError).code != NSURLErrorCancelled {
            showStatus("工作台页面没有打开", detail: "后台服务可能刚刚停止。", isError: true)
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if let port { load(port: port) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        runUITestIfRequested()
    }

    // MARK: Developer self-test (the variables are never set for users)

    /// BROWSER_WORKBENCH_UI_TEST=script.js runs once the workbench page has loaded, with the
    /// page's globals in scope; its result and snapshots go to BROWSER_WORKBENCH_UI_TEST_OUT.
    private var uiTestStarted = false
    private var uiTestOutput: URL? {
        guard AppPaths.environment["BROWSER_WORKBENCH_UI_TEST"] != nil, let out = AppPaths.environment["BROWSER_WORKBENCH_UI_TEST_OUT"] else { return nil }
        return URL(fileURLWithPath: out, isDirectory: true)
    }

    private func runUITestIfRequested() {
        guard port != nil, !uiTestStarted, let output = uiTestOutput,
              let script = try? String(contentsOfFile: AppPaths.environment["BROWSER_WORKBENCH_UI_TEST"]!, encoding: .utf8) else { return }
        uiTestStarted = true
        try? FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        webView.callAsyncJavaScript(script, arguments: [:], in: nil, in: .page) { result in
            let report: [String: Any]
            switch result {
            case .success(let value): report = ["ok": true, "result": value]
            case .failure(let error): report = ["ok": false, "error": String(describing: error)]
            }
            let data = (try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])) ?? Data("{}".utf8)
            try? data.write(to: output.appendingPathComponent("result.json"))
        }
    }

    private func handleUITest(_ type: String, _ body: [String: Any], replyHandler: @escaping (Any?, String?) -> Void) {
        guard let output = uiTestOutput else { return replyHandler(nil, "forbidden") }
        switch type {
        case "test.snapshot":
            guard let name = body["name"] as? String, name.range(of: "^[a-z0-9-]{1,40}$", options: .regularExpression) != nil else {
                return replyHandler(nil, "bad request")
            }
            webView.takeSnapshot(with: nil) { image, _ in
                if let tiff = image?.tiffRepresentation, let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
                    try? png.write(to: output.appendingPathComponent(name + ".png"))
                }
                replyHandler(["ok": image != nil], nil)
            }
        case "test.quit":
            replyHandler(["ok": true], nil)
            (NSApp.delegate as? AppDelegate)?.quitForTest(stopEnvironments: body["stopEnvironments"] as? Bool ?? false)
        default:
            replyHandler(nil, "unknown request")
        }
    }

    // MARK: Downloads ("下载到电脑")

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let folder = AppPaths.downloadsDirectory
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let destination = uniqueURL(in: folder, name: safeFileName(suggestedFilename))
        downloads[ObjectIdentifier(download)] = destination
        completionHandler(destination)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        revealable.insert(url.path)
        notifyPage(event: "workbench-native-download", detail: ["ok": true, "name": url.lastPathComponent, "path": url.path])
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let url = downloads.removeValue(forKey: ObjectIdentifier(download))
        if let url { try? FileManager.default.removeItem(at: url) }
        notifyPage(event: "workbench-native-download", detail: ["ok": false, "name": url?.lastPathComponent ?? ""])
    }

    private func safeFileName(_ name: String) -> String {
        var cleaned = name.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
        while cleaned.hasPrefix(".") { cleaned.removeFirst() }
        return cleaned.isEmpty ? "下载文件" : cleaned
    }

    private func uniqueURL(in folder: URL, name: String) -> URL {
        let base = (name as NSString).deletingPathExtension, ext = (name as NSString).pathExtension
        var candidate = folder.appendingPathComponent(name)
        var index = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = folder.appendingPathComponent(ext.isEmpty ? "\(base) (\(index))" : "\(base) (\(index)).\(ext)")
            index += 1
        }
        return candidate
    }

    // MARK: Page UI requests

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, url.scheme == "http" || url.scheme == "https", !isWorkbench(url) {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = "传入环境"
        guard let window else { return completionHandler(nil) }
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    // MARK: Native bridge: window.webkit.messageHandlers.workbench.postMessage({type,...})

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        let origin = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame, let port, origin.protocol == "http", origin.host == "127.0.0.1", origin.port == port,
              let body = message.body as? [String: Any], let type = body["type"] as? String else {
            return replyHandler(nil, "forbidden")
        }
        let pasteboard = NSPasteboard.general
        switch type {
        case "clipboard.read":
            replyHandler(readPasteboard(pasteboard), nil)
        case "clipboard.writeText":
            guard let text = body["text"] as? String else { return replyHandler(nil, "bad request") }
            pasteboard.clearContents()
            pasteboard.setString(text, forType: .string)
            replyHandler(["ok": true], nil)
        case "openExternal":
            guard let string = body["url"] as? String, let url = URL(string: string), url.scheme == "https" || url.scheme == "http" else {
                return replyHandler(nil, "bad request")
            }
            NSWorkspace.shared.open(url)
            replyHandler(["ok": true], nil)
        case "revealFile":
            guard let path = body["path"] as? String, revealable.contains(path) else { return replyHandler(nil, "forbidden") }
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            replyHandler(["ok": true], nil)
        case _ where type.hasPrefix("test."):
            handleUITest(type, body, replyHandler: replyHandler)
        default:
            replyHandler(nil, "unknown request")
        }
    }

    /// Same priority as the page's own clipboard code: an image first, then text.
    private func readPasteboard(_ pasteboard: NSPasteboard) -> [String: Any] {
        var result: [String: Any] = [:]
        if let files = pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL], !files.isEmpty {
            // Finder copies put the file icon on the pasteboard too; never paste that as a picture.
            result["files"] = files.map(\.lastPathComponent)
            return result
        }
        if let png = pasteboard.data(forType: .png) {
            result["image"] = png.base64EncodedString()
        } else if let tiff = pasteboard.data(forType: .tiff), let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
            result["image"] = png.base64EncodedString()
        }
        if let text = pasteboard.string(forType: .string) { result["text"] = text }
        return result
    }

    // MARK: Window

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // Closing the window keeps the app (and running environments) alive; the Dock icon reopens it.
        sender.orderOut(nil)
        return false
    }
}

func jsString(_ value: String) -> String {
    let data = try? JSONSerialization.data(withJSONObject: [value])
    let array = data.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
    return String(array.dropFirst().dropLast())
}

/// Native page shown before the backend is reachable or after it fails.
enum StatusPage {
    static func html(message: String, detail: String, isError: Bool) -> String {
        let escape: (String) -> String = {
            $0.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
        }
        let actions = isError
            ? "<div class=actions><a class=primary href='workbench-native://retry'>重试</a><a href='workbench-native://logs'>查看日志</a></div>"
            : "<div class=spinner></div>"
        return """
        <!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
        :root{color-scheme:light}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f7f4;color:#203a33;
        font:15px -apple-system,"PingFang SC",sans-serif}.card{text-align:center;max-width:460px;padding:40px}
        .mark{width:64px;height:64px;margin:0 auto 22px;border-radius:16px;background:#21644e;color:#fff;display:grid;place-items:center;
        font:600 32px "PingFang SC",sans-serif}h1{font-size:20px;font-weight:600;margin:0 0 10px}p{color:#85918a;line-height:1.7;margin:0}
        .spinner{width:22px;height:22px;margin:26px auto 0;border:3px solid #e3e8e1;border-top-color:#21644e;border-radius:50%;
        animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.actions{margin-top:26px;display:flex;gap:10px;justify-content:center}
        a{padding:9px 18px;border-radius:9px;border:1px solid #e3e8e1;color:#203a33;text-decoration:none;background:#fff}
        a.primary{background:#21644e;border-color:#21644e;color:#fff}</style>
        <div class=card><div class=mark>境</div><h1>\(escape(message))</h1><p>\(escape(detail))</p>\(actions)</div></html>
        """
    }
}
