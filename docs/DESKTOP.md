# Mac 应用（v0.7）的结构与取舍

v0.7 把原来“在浏览器里打开 http://127.0.0.1:8766”的工作台，做成可以从 DMG 安装、双击打开的独立 Mac 应用 **Browser Workbench.app**。浏览器环境本身的实现（Docker 容器里的标准 Firefox + mihomo + noVNC）没有改变。

## 组成

```
Browser Workbench.app/Contents/
  MacOS/BrowserWorkbench        Swift 原生外壳（AppKit + WKWebView），约 0.3 MB
  Resources/python/             自带的 CPython 3.12（python-build-standalone）及固定版本依赖
  Resources/backend/            工作台后端（workbench/）、界面（static/）、容器构建文件（runtime/）
  Resources/runtime-image/      预先构建好的浏览器组件镜像（gzip 压缩的 docker save 文件，可选）
```

运行时：

1. 外壳启动自带的 Python：`python -m workbench.desktop --data-dir ~/Library/Application Support/BrowserWorkbench --exit-on-stdin-eof`。
2. 后端在 127.0.0.1 的随机空闲端口监听，就绪后向外壳输出一行 `WORKBENCH_READY {"port": …}`。
3. 外壳在自己的窗口里用 WKWebView 打开这个本机地址。界面与网页版是同一套 HTML/JS。
4. 外壳一直持有后端的 stdin。应用退出、崩溃或被强制结束时管道关闭，后端随之退出，不会在后台遗留看不见的服务。
5. 同一个数据文件夹只允许一个后端（`.workbench.lock` 文件锁），避免两个副本同时管理同一批容器。

## 为什么这样选

| 问题 | 选择 | 理由 |
| --- | --- | --- |
| 桌面框架 | Swift + WKWebView | 本机有 Xcode，无需 Node/Rust；外壳只有几百 KB；剪贴板、下载、文件选择、外部链接都能走原生接口，避开浏览器权限弹窗。Electron 也可行，但会多 150 MB 以上，且仍要另外打包 Python。 |
| 后端 | 保留现有 Python/FastAPI，随应用自带解释器 | 已有 100+ 项测试覆盖的逻辑不重写；使用者不再需要安装 Python、执行 pip 或打开终端。 |
| 浏览器环境 | 暂时保留 Docker | 每个环境的 CPU/内存上限、暂停/唤醒、隔离都依赖容器；在 Mac 上去掉 Docker 意味着自己维护 Linux 虚拟机（见下文“以后可以做”）。 |
| 浏览器组件 | DMG 自带预构建镜像，首次 `docker load` | 首次准备不再访问 Docker Hub、Debian、PyPI、GitHub。实测在本机从源码构建时，Debian 软件源经代理下载中途断开导致失败，正是内测机最可能卡住的环节之一。 |
| 数据位置 | `~/Library/Application Support/BrowserWorkbench` | macOS 应用的标准位置；不在 iCloud 同步的“文稿”里；路径与旧版不同，所以旧版数据只能通过“导入”复制过来，不会被新版改动。 |

## 安装与首次启动流程

1. 打开 DMG，把应用拖进“应用程序”。
2. 首次打开时 macOS 可能拦截（未使用 Apple 开发者证书），在“系统设置 → 隐私与安全性”点“仍要打开”。
3. 应用自动检查 Docker：
   - 找到 Docker Desktop 或 OrbStack：自动打开并等待（最多 10 分钟，期间界面提示在 Docker 窗口完成首次设置）；
   - 没有 Docker：界面给出按芯片区分的官方下载链接和三步说明，安装好后自动继续；
   - 只有命令行 Docker（例如 Colima）：可以直接使用，但需使用者先启动它。
4. 引擎就绪后，若没有 `local-browser-workbench:0.7.0` 镜像，就把应用自带的镜像载入 Docker，界面显示百分比；自带镜像损坏或缺失时才退回联网构建。
5. 显示 Docker 可分配内存，以及按每个 2 GB 估算约能同时运行几个环境。工作台不会自动修改 Docker 的全局设置。

应用从 Finder 启动时 PATH 只有系统目录，所以后端会在 Docker Desktop、OrbStack、Homebrew 的标准位置寻找 docker 命令，并把它所在目录加入子进程 PATH（否则 docker 的凭据助手找不到，联网构建会失败）。

## 退出与环境

- 关窗口：应用和环境都继续运行，点 Dock 图标重新打开。
- ⌘Q：若有环境在运行，会询问“停止环境并退出 / 保留运行并退出 / 取消”。停止会正常关闭 Firefox 以写盘（和单个环境的“停止”相同）。
- 注销、重启、关机：不弹询问，直接正常停止环境后退出。
- 保留运行时，环境容器继续在 Docker 中占用内存；下次打开应用会自动识别并可继续使用。

## 外观

- 窗口使用透明的统一标题栏（52 pt）：页面的侧栏和顶栏延伸到标题栏下面，红绿灯按钮位于侧栏顶部，顶栏区域仍可拖动窗口。网页里 `html.native-app` 会为这条带预留空间，交互控件都不放在里面。
- 颜色全部是 `static/style.css` 顶部的变量，按 `prefers-color-scheme` 切换浅色 / 深色，跟随系统设置。
- 设计检查：`tests/ui/run_screens.sh` 用 `tests/ui/seed_demo.py` 生成的假数据，在真实应用窗口里截取每个页面、弹窗和浏览器画面的浅色 / 深色图（截图包含标题栏按钮）。

## 原生桥接

页面通过 `window.webkit.messageHandlers.workbench` 请求以下原生功能（仅接受来自本机工作台主框架的请求）：

- `clipboard.read`：读取主电脑剪贴板的图片（PNG/TIFF 转 PNG）或文字，用于“从电脑粘贴”。复制的是 Finder 文件时提示改用拖入或文件传输。
- `clipboard.writeText`：“复制到电脑”及“复制环境路径”。
- `openExternal`：用默认浏览器打开外部链接（例如 Docker 下载页）。
- `revealFile`：在 Finder 中显示刚下载的文件（只限本窗口下载过的文件）。

“下载到电脑”由 WKDownload 处理，保存到“下载”文件夹，同名自动加序号，完成后提示并可在 Finder 中显示。网页里的文件选择框使用系统打开面板。把文件从 Finder 拖到环境画面上，等同于粘贴文件：单张 PNG 直接粘贴进网页，其他文件放入“电脑传入文件”。

## 外壳与后端之间的控制接口

外壳生成一个随机密钥，经环境变量交给后端。`/control/summary`（运行中的环境）和 `/control/stop-all`（退出时停止全部）只接受带这个密钥、且没有 Origin 头的请求；网页里的令牌无法调用它们。

## 构建

见 [BUILD.md](BUILD.md)。构建产物放在 `~/Library/Caches/BrowserWorkbenchBuild`，只把最终 DMG 放进项目的 `dist/`：项目所在的“文稿”由 iCloud 同步，并且 iCloud 给文件附加的 Finder 信息会让 codesign 拒绝签名。

## 以后可以做

- **不再依赖 Docker Desktop**：在应用里内置一个基于 Apple Virtualization.framework 的轻量 Linux 虚拟机（例如 Lima），自带磁盘镜像，由应用自己管理 CPU/内存。好处是安装只剩一个 DMG、不需要管理员密码和 Docker 的条款；代价是 DMG 更大、要自己处理虚拟机更新和文件共享权限，需要单独开发和在多台 Mac 上验收。
- **Apple 开发者证书签名与公证**（每年 99 美元）：首次打开不再被拦截。构建脚本已支持 `SIGN_IDENTITY`，公证还需要启用 hardened runtime 并逐一检查 Python 扩展模块。
- **Intel Mac 版本**：脚本已能为 x86_64 编译外壳并下载对应的 Python 与依赖，但镜像需要在 Intel Mac（或 Docker buildx 模拟）上构建导出，目前没有实际验证。
