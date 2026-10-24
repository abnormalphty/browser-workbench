import AppKit

/// "导入旧版工作台数据…": copies a source-version `data` folder into the app's
/// data folder via `python -m workbench.migrate`. The old folder is only read.
final class LegacyImport {
    private let backend: Backend
    private let window: MainWindowController

    init(backend: Backend, window: MainWindowController) {
        self.backend = backend
        self.window = window
    }

    func begin() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "检查这个文件夹"
        panel.message = "请选择旧版工作台里的 data 文件夹（里面有 workbench.sqlite3）。只会读取，不会修改它。"
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        guard let host = window.window else { return }
        panel.beginSheetModal(for: host) { [self] result in
            guard result == .OK, let source = panel.url else { return }
            run(["inspect", source.path]) { [self] info in
                guard let info else { return }
                guard (info["started"] as? Int ?? 0) == 0 else {
                    return show("旧版还有环境在运行", "请先在旧版工作台里停止全部环境（包括低功耗的），再导入，避免复制到正在写入的登录数据。")
                }
                run(["has-data", AppPaths.dataDirectory.path]) { [self] target in
                    guard let target else { return }
                    if target["has_data"] as? Bool == true {
                        return show("新版里已经有数据", "为避免覆盖，只能导入到还没有环境和订阅的新版应用中。")
                    }
                    confirm(info, source: source)
                }
            }
        }
    }

    private func confirm(_ info: [String: Any], source: URL) {
        let size = ByteCountFormatter.string(fromByteCount: Int64(info["size_bytes"] as? Int ?? 0), countStyle: .file)
        let alert = NSAlert()
        alert.messageText = "导入 \(info["environments"] as? Int ?? 0) 个环境和 \(info["nodes"] as? Int ?? 0) 个节点？"
        alert.informativeText = "会复制约 \(size) 到新版的数据文件夹，包括订阅、登录数据和传输文件。原来的文件夹保持不变，旧版仍可打开。\n\n导入后请在新版里继续使用：之后在旧版里做的改动不会同步过来。"
        alert.addButton(withTitle: "复制导入")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        window.showStatus("正在导入旧版数据…", detail: "正在复制 \(size)，请不要关闭应用。")
        backend.stop { [self] in
            run(["copy", source.path, AppPaths.dataDirectory.path]) { [self] result in
                backend.start()
                guard let result else { return }
                show("导入完成", "已导入 \(result["environments"] as? Int ?? 0) 个环境。旧版文件夹没有改动；确认新版一切正常后，可以自行决定是否删除它。")
            }
        }
    }

    /// Runs the migration tool off the main thread; reports its JSON or shows its error.
    private func run(_ arguments: [String], completion: @escaping ([String: Any]?) -> Void) {
        let process = AppPaths.pythonProcess(arguments: ["-m", "workbench.migrate"] + arguments)
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            var json: [String: Any]?
            do {
                try process.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            } catch {}
            DispatchQueue.main.async { [self] in
                guard let json, json["ok"] as? Bool == true else {
                    show("没有导入", json?["error"] as? String ?? "导入工具没有正常运行，旧数据没有改动。")
                    return completion(nil)
                }
                completion(json)
            }
        }
    }

    private func show(_ title: String, _ message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
    }
}
