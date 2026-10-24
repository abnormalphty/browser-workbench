import Foundation

/// Where the app keeps its files. Overridable for tests so they never touch real data.
enum AppPaths {
    static let environment = ProcessInfo.processInfo.environment

    static var dataDirectory: URL {
        if let custom = environment["BROWSER_WORKBENCH_DATA_DIR"], !custom.isEmpty {
            return URL(fileURLWithPath: custom, isDirectory: true)
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("BrowserWorkbench", isDirectory: true)
    }

    static var logDirectory: URL {
        if let custom = environment["BROWSER_WORKBENCH_LOG_DIR"], !custom.isEmpty {
            return URL(fileURLWithPath: custom, isDirectory: true)
        }
        return FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/BrowserWorkbench", isDirectory: true)
    }

    static var downloadsDirectory: URL {
        if let custom = environment["BROWSER_WORKBENCH_DOWNLOADS_DIR"], !custom.isEmpty {
            return URL(fileURLWithPath: custom, isDirectory: true)
        }
        return FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
    }

    static var backendLog: URL { logDirectory.appendingPathComponent("backend.log") }
    static var resources: URL { Bundle.main.resourceURL! }
    static var python: URL { resources.appendingPathComponent("python/bin/python3") }
    static var backend: URL { resources.appendingPathComponent("backend", isDirectory: true) }

    static var imageArchive: URL? {
        let url = resources.appendingPathComponent("runtime-image/browser-runtime.tar.gz")
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    /// The bundled interpreter, isolated from any Python the user installed.
    static func pythonProcess(arguments: [String], extraEnvironment: [String: String] = [:]) -> Process {
        let process = Process()
        process.executableURL = python
        process.arguments = ["-E", "-s", "-B", "-X", "utf8"] + arguments
        process.currentDirectoryURL = backend
        var env = environment.filter { !$0.key.hasPrefix("PYTHON") }
        for (key, value) in extraEnvironment { env[key] = value }
        process.environment = env
        return process
    }
}

/// Runs the Python backend and reports when it is reachable.
final class Backend {
    enum State: Equatable {
        case stopped
        case starting
        case ready(port: Int)
        case failed(String)
    }

    struct Summary {
        var running = 0
        var paused = 0
        var starting = 0
        var names: [String] = []
        var active: Int { running + paused + starting }
    }

    var onStateChange: ((State) -> Void)?
    private(set) var state: State = .stopped {
        didSet { if state != oldValue { onStateChange?(state) } }
    }

    private var process: Process?
    private var input: Pipe?
    private var log: FileHandle?
    private var pendingOutput = Data()
    private var lockedOut = false
    private var stopping = false
    private var stopWaiters: [() -> Void] = []
    private var launchCount = 0
    let controlToken: String = {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }()

    var port: Int? {
        if case .ready(let port) = state { return port }
        return nil
    }

    func start() {
        guard process == nil else { return }
        lockedOut = false
        stopping = false
        pendingOutput = Data()
        state = .starting
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: AppPaths.dataDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try fm.createDirectory(at: AppPaths.logDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        } catch {
            state = .failed("无法创建数据文件夹：\(error.localizedDescription)")
            return
        }
        guard fm.isExecutableFile(atPath: AppPaths.python.path) else {
            state = .failed("应用内的运行组件不完整，请重新安装 Browser Workbench。")
            return
        }
        openLog()

        var extra = ["WORKBENCH_CONTROL_TOKEN": controlToken, "WORKBENCH_MODE": "desktop", "WORKBENCH_APP_VERSION": AppPaths.version]
        if let archive = AppPaths.imageArchive { extra["WORKBENCH_IMAGE_ARCHIVE"] = archive.path }
        let process = AppPaths.pythonProcess(
            arguments: ["-m", "workbench.desktop", "--data-dir", AppPaths.dataDirectory.path, "--exit-on-stdin-eof"],
            extraEnvironment: extra)
        let output = Pipe(), errors = Pipe(), input = Pipe()
        process.standardOutput = output
        process.standardError = errors
        process.standardInput = input
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }  // EOF; otherwise this spins
            DispatchQueue.main.async { self?.consume(data) }
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async { self?.writeLog(data) }
        }
        process.terminationHandler = { [weak self] finished in
            let status = finished.terminationStatus
            DispatchQueue.main.async { self?.didExit(status: status) }
        }
        do {
            try process.run()
        } catch {
            state = .failed("后台服务无法启动：\(error.localizedDescription)")
            return
        }
        self.process = process
        self.input = input
        launchCount += 1
        let launch = launchCount
        // Python normally answers within seconds; never leave the window spinning forever.
        DispatchQueue.main.asyncAfter(deadline: .now() + 90) { [weak self] in
            guard let self, self.launchCount == launch, self.state == .starting, self.process != nil else { return }
            self.stop { [weak self] in
                self?.state = .failed("后台服务启动超时。可以点重试；如果反复出现，请查看日志。")
            }
        }
    }

    /// Ends the backend: closing its stdin is the request, SIGTERM/SIGKILL the fallback.
    func stop(completion: (() -> Void)? = nil) {
        guard let process else {
            completion?()
            return
        }
        if let completion { stopWaiters.append(completion) }
        if stopping { return }
        stopping = true
        try? input?.fileHandleForWriting.close()
        process.terminate()
        // Only this process: by now a restart may already have launched a new one.
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak process] in
            guard let process, process.isRunning else { return }
            kill(process.processIdentifier, SIGKILL)
        }
    }

    func restart() {
        stop { [weak self] in self?.start() }
    }

    // MARK: Native control API (separate secret from the page token)

    private func control(_ path: String, method: String = "GET", timeout: TimeInterval, completion: @escaping ([String: Any]?) -> Void) {
        guard let port, let url = URL(string: "http://127.0.0.1:\(port)/control/\(path)") else {
            completion(nil)
            return
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue(controlToken, forHTTPHeaderField: "X-Workbench-Control")
        let session = URLSession(configuration: .ephemeral)
        session.dataTask(with: request) { data, response, _ in
            var result: [String: Any]?
            if let data, (response as? HTTPURLResponse)?.statusCode == 200 {
                result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            }
            DispatchQueue.main.async { completion(result) }
        }.resume()
        session.finishTasksAndInvalidate()
    }

    func summary(completion: @escaping (Summary?) -> Void) {
        control("summary", timeout: 15) { json in
            guard let json else { return completion(nil) }
            completion(Summary(running: json["running"] as? Int ?? 0, paused: json["paused"] as? Int ?? 0,
                               starting: json["starting"] as? Int ?? 0, names: json["names"] as? [String] ?? []))
        }
    }

    func stopAllEnvironments(completion: @escaping (Bool) -> Void) {
        control("stop-all", method: "POST", timeout: 120) { json in completion(json?["ok"] as? Bool ?? false) }
    }

    // MARK: Output handling

    private func consume(_ data: Data) {
        guard !data.isEmpty else { return }
        writeLog(data)
        pendingOutput.append(data)
        while let newline = pendingOutput.firstIndex(of: 0x0A) {
            let line = String(decoding: pendingOutput[pendingOutput.startIndex..<newline], as: UTF8.self)
            pendingOutput.removeSubrange(pendingOutput.startIndex...newline)
            handle(line: line)
        }
    }

    private func handle(line: String) {
        if line.hasPrefix("WORKBENCH_READY "),
           let json = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(16).utf8)) as? [String: Any],
           let port = json["port"] as? Int {
            state = .ready(port: port)
        } else if line.hasPrefix("WORKBENCH_ERROR ") && line.contains("locked") {
            lockedOut = true
        }
    }

    private func didExit(status: Int32) {
        process = nil
        input = nil
        let wasStopping = stopping
        stopping = false
        if wasStopping {
            state = .stopped
        } else if lockedOut {
            state = .failed("另一个 Browser Workbench 正在使用同一个数据文件夹。请先退出另一个窗口或副本（例如仍在磁盘映像里运行的那个），再点重试。")
        } else {
            state = .failed("后台服务意外停止（代码 \(status)）。浏览器环境不受影响，可以点重试重新连接。")
        }
        try? log?.close()
        log = nil
        let waiters = stopWaiters
        stopWaiters = []
        waiters.forEach { $0() }
    }

    private func openLog() {
        let fm = FileManager.default
        let url = AppPaths.backendLog
        if let size = (try? fm.attributesOfItem(atPath: url.path))?[.size] as? Int, size > 5_000_000 {
            let previous = url.appendingPathExtension("1")
            try? fm.removeItem(at: previous)
            try? fm.moveItem(at: url, to: previous)
        }
        if !fm.fileExists(atPath: url.path) {
            fm.createFile(atPath: url.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        log = try? FileHandle(forWritingTo: url)
        _ = try? log?.seekToEnd()
        writeLog(Data("\n--- \(Date()) Browser Workbench \(AppPaths.version) ---\n".utf8))
    }

    private func writeLog(_ data: Data) {
        guard !data.isEmpty else { return }
        try? log?.write(contentsOf: data)
    }
}
