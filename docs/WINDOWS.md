# Windows 版说明

Windows 版和 Mac 应用共用同一份后端、网页界面和浏览器组件镜像，只有窗口外壳、安装方式和几处与系统有关的细节不同。

## 安装与使用

- 安装包：`Browser-Workbench-VERSION-x64-Setup.exe`，适用于 64 位的 Windows 10（22H2）或 Windows 11。
- 只为当前用户安装到 `%LOCALAPPDATA%\Programs\Browser Workbench`，不需要管理员权限；在开始菜单和桌面放快捷方式，可在“设置 → 应用”里卸载。
- 第一次运行安装包时，Windows 可能提示“Windows 已保护你的电脑”：点“更多信息 → 仍要运行”。原因是安装包没有代码签名证书。打开了“智能应用控制”的电脑会直接拦下未签名的程序，这种情况只能购买代码签名证书解决。
- 需要 Docker Desktop。没有安装时，应用会给出官方下载链接和步骤：安装时保持“Use WSL 2”勾选，按提示重启；打开 Docker Desktop 同意条款后，回到应用会自动继续，并载入安装包自带的浏览器组件。Docker Desktop 需要电脑开启虚拟化，并安装 WSL 2（安装程序会提示）。浏览器组件是 Linux 镜像：Docker Desktop 被切换到“Windows 容器”时，应用不会去载入组件，而是提示在任务栏 Docker 图标的右键菜单里选择“Switch to Linux containers…”。
- 窗口用 Windows 自带的 Microsoft Edge WebView2 显示。Windows 11 和绝大多数 Windows 10 已经有它；没有时安装程序会联网安装。
- 关闭窗口即退出应用。有环境在运行时会询问：停止环境并退出、保留运行并退出、或取消。再次打开快捷方式会回到已经打开的窗口。
- 窗口左上角的系统菜单（点图标或按 Alt+空格）里有“打开数据文件夹”和“打开日志文件夹”。

## 数据放在哪里

| 内容 | 位置 |
| --- | --- |
| 数据库、订阅、账号记录、文件传输文件夹 | `%LOCALAPPDATA%\BrowserWorkbench\Data` |
| 日志 | `%LOCALAPPDATA%\BrowserWorkbench\Logs\backend.log` |
| 窗口自身的浏览数据（只有工作台页面） | `%LOCALAPPDATA%\BrowserWorkbench\WebView2` |
| 各环境的 Firefox 配置与登录状态 | Docker 存储卷 `workbench-<范围>-<环境编号>` |

Firefox 的登录数据放在 Docker 存储卷里，而不是 Windows 文件夹，原因有两个：从 Windows 共享进 Linux 容器的文件夹不能改所有者（容器启动时要改），而且 Firefox 依赖的 SQLite 文件锁在这种共享上不可靠、速度也慢。只有“电脑传入文件”“环境下载文件”两个文件夹仍在 Windows 数据目录里，方便在资源管理器里打开。

所以：卸载应用不会删除任何数据；但在 Docker Desktop 里“重置 / 清除数据”或删除对应存储卷，会清掉这些环境的登录状态。删除环境时，应用会一并删除它的存储卷。

## 结构

```
Browser Workbench\
  BrowserWorkbench.exe        窗口外壳（.NET Framework 4.8，Windows 10/11 自带）+ WebView2
  Microsoft.Web.WebView2.*.dll, runtimes\win-x64\native\WebView2Loader.dll
  python\                     自带 CPython 3.12（与 Mac 版同一构建来源）及 Windows 版依赖
  backend\                    workbench\、static\、runtime\（与 Mac 版相同）
  runtime-image\              x64 浏览器组件镜像（docker load 离线载入）
  licenses\                   WebView2 SDK、NSIS 许可
```

- 外壳启动 `python\python.exe -E -s -B -X utf8 -m workbench.desktop --data-dir … --exit-on-stdin-eof`，读到 `WORKBENCH_READY {"port":…}` 后打开 `http://127.0.0.1:端口/`；关闭标准输入即请后端退出，8 秒不退则结束进程。与 Mac 外壳是同一套约定。
- 网页通过 `window.workbenchBridge.call(类型, 数据)` 请求原生功能（剪贴板读写、用默认浏览器打开链接、在资源管理器里显示下载的文件），只接受来自本机工作台主框架的请求。外壳注入 `window.workbenchNative = {version, platform: 'windows'}`，页面据此使用 Windows 的说法（资源管理器、Ctrl+V）和 Docker Desktop 的安装步骤，不需要 Mac 的标题栏占位。
- “下载到电脑”由 WebView2 的下载事件接管，保存到“下载”文件夹，同名时自动编号，不弹出浏览器下载面板。
- 后端在 Windows 上：用 `CREATE_NO_WINDOW` 启动 docker 命令（否则每次都会闪一个命令行窗口）；在 `C:\Program Files\Docker\Docker` 找 Docker Desktop；数据文件夹用 `msvcrt.locking` 加锁防止两个后端同时使用；文件传输没有 `dir_fd`，改为逐级用 `lstat` 检查，拒绝符号链接和目录连接点。

## 构建（在 Mac 上）

```sh
scripts/fetch_windows_tools.sh          # .NET SDK、NSIS、Windows 版 Python，都放在构建缓存里
scripts/export_runtime_image.sh x86_64  # 在 Apple 芯片的 Mac 上模拟构建 x64 浏览器组件（较慢）
scripts/build_windows.sh --with-image ~/Library/Caches/BrowserWorkbenchBuild/runtime-image/browser-runtime-x86_64.tar.gz
```

产物：`dist/Browser-Workbench-VERSION-x64-Setup.exe` 及 `.sha256`。窗口外壳从项目外的副本编译（`dotnet` 会在项目旁写 `obj/`、`bin/`，而项目在 iCloud 同步的“文稿”里）；打包后同样经过 `scripts/check_bundle.py` 的隐私检查。

## 验证状况

2026-11-05 在一台 Apple 芯片 Mac（Docker Desktop 29.9）上验证过的：

- 后端的 Windows 分支：`tests/test_windows.py` 与按 Windows 方式重跑的文件传输检查（在任何电脑上把系统当作 Windows 运行），包括 Docker Desktop 处于“Windows 容器”模式时的提示；基础测试共 134 项通过。
- 窗口外壳用 .NET SDK 编译，0 个警告、0 个错误；安装包能生成，内容核对过：外壳、Python 与 `.pyd` 依赖都是 64 位 Windows 版，自带的浏览器组件与导出文件逐字节相同，隐私检查通过。
- x64 浏览器组件：用后台自己的载入流程（`docker load`）载入安装包里那份文件后，在模拟的 x64 环境里、按 Windows 的方式（Firefox 登录数据放在 Docker 存储卷）运行容器测试，`tests/integration_runtime.py` 7 项、`tests/integration_transfers.py` 5 项全部通过，结束后没有留下存储卷。模拟运行比真机慢，重启后的页面检查放宽了等待时间（第一次按 10 秒等待时有一项超时）。
- 两种架构的组件出自同一份 Dockerfile，Debian 软件包版本一致（x64 只多 3 个该架构专有的库）。

2026-11-08 在 GitHub 提供的 Windows 机器（`windows-latest`）上验证过的。工作流是 `.github/workflows/windows.yml`，在代码推到 `windows-check` 分支、且安装包已放进同版本的草稿发布时运行：

- Windows 版 Python 3.12 上的基础测试 134 项通过。其中 12 项只检查 Mac 路径或导入旧版 Mac 数据，按设计跳过。
  - 第一次运行（2026-11-05）查出两个问题：Windows 没有系统时区库；读写文本文件默认不是 UTF-8。
  - 两个问题都已修复：依赖里加入了 `tzdata`，读写文本文件一律指定 UTF-8。
- 安装：从草稿发布下载安装包（SHA-256 与本地构建一致）并静默安装。程序文件和开始菜单快捷方式都已就位，自带的 Python 能读取时区。
- 自检：启动窗口，在 WebView2 里运行 `tests/ui/windows_smoke.js`，6 项全部通过：
  - 页面运行在 Windows 外壳里，原生桥可用；
  - 自带后端返回了正确的版本和平台；
  - 没有 Mac 标题栏占位，使用 Windows 的说法；
  - 剪贴板经原生桥往返，包括中文；
  - 拒绝在资源管理器里显示不是本应用保存的文件；
  - Docker 不可用时给出说明（这台机器装了 Docker 命令，但后台服务没有运行）。

  数据目录用的是带空格的路径。
- 退出与卸载：自检后应用自行退出，后端也随之结束；静默卸载后程序文件被删除。

这些机器不能运行 Linux 容器，所以浏览器环境本身还没有在 Windows 上运行过。

还需要在真实 Windows 电脑上验证的：

- 用安装向导（非静默）安装、升级与卸载；SmartScreen 提示。
- WebView2 窗口的其余原生功能：下载到电脑、在资源管理器中显示、系统菜单、深色标题栏、窗口位置记忆、再次打开回到已有窗口；以及退出时的询问。
- Docker Desktop 的查找、启动与首次设置。
- 在真实的 Docker Desktop（WSL 2）里载入组件、启动环境并显示画面。
- 文件传输文件夹在 Windows 共享下的读写。
- 用户名含中文或空格时，Docker 能否共享文件传输文件夹。
