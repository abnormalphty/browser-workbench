# Windows 版说明

Windows 版和 Mac 应用共用同一份后端、网页界面和浏览器组件镜像，只有窗口外壳、安装方式和几处与系统有关的细节不同。

## 安装与使用

- 安装包：`Browser-Workbench-VERSION-x64-Setup.exe`，适用于 64 位的 Windows 10（22H2）或 Windows 11。
- 只为当前用户安装，不需要管理员权限；在开始菜单和桌面放快捷方式，可在“设置 → 应用”里卸载。
- 安装向导会问两个位置（见下文“数据放在哪里”）：
  - **安装位置**：程序和自带的浏览器组件，默认 `%LOCALAPPDATA%\Programs\Browser Workbench`，可以改到其他磁盘。选的文件夹里已有其他文件时，程序装进其中新建的 `Browser Workbench` 文件夹，因为升级和卸载会删除程序文件夹里的程序文件。写不进去的位置（比如需要管理员权限的 `C:\Program Files`）会提示换一个。以后重新运行安装包、选别的位置，旧位置的程序会被删掉，数据不受影响。
  - **数据存放位置**：只在第一次安装（还没有工作台数据）时出现，默认 `%LOCALAPPDATA%\BrowserWorkbench`。已有数据时不再询问，数据留在原处，需要时在应用里移动。
- 静默安装：`Setup.exe /S /DATA=数据位置 /D=程序位置`。`/D=` 必须放在最后、不加引号；`/DATA=` 同样只在还没有数据时生效。
- 第一次运行安装包时，Windows 可能提示“Windows 已保护你的电脑”：点“更多信息 → 仍要运行”。原因是安装包没有代码签名证书。打开了“智能应用控制”的电脑会直接拦下未签名的程序，这种情况只能购买代码签名证书解决。
- 需要 Docker Desktop。没有安装时，应用可以自动安装（见下一节），也可以点“手动安装”从官网下载；装好后应用会自动继续，并载入安装包自带的浏览器组件。Docker Desktop 需要电脑开启 CPU 虚拟化和 WSL 2。
- 浏览器组件是 Linux 镜像。Docker Desktop 处于“Windows 容器”模式时，应用会先用 `docker desktop engine use linux` 自动切回（旧版用 `DockerCli.exe -SwitchLinuxEngine`）；切不过去时，才提示在任务栏 Docker 图标的右键菜单里选“Switch to Linux containers…”。
- 窗口用 Windows 自带的 Microsoft Edge WebView2 显示。Windows 11 和绝大多数 Windows 10 已经有它；没有时安装程序会联网安装。
- 关闭窗口即退出应用。有环境在运行时会询问：停止环境并退出、保留运行并退出、或取消。再次打开快捷方式会回到已经打开的窗口。
- 窗口左上角的系统菜单（点图标或按 Alt+空格）里有“打开数据文件夹”和“打开日志文件夹”。

## 自动安装 Docker Desktop

点“同意并自动安装”即表示用户同意 [Docker 订阅服务协议](https://www.docker.com/legal/docker-subscription-service-agreement/)。个人使用、教育和小公司免费；员工超过 250 人或年收入超过 1000 万美元的公司需要付费订阅。这次同意只对这一次安装有效：Docker Desktop 以后被卸载时，应用会重新询问，不会自己重装。

同意后，后端（`workbench/docker_setup.py`）按下面的顺序准备，每一步的进度都显示在“运行组件”里：

1. **检查电脑**：Windows 版本至少为 10 22H2；CPU 虚拟化已开启（有正在运行的虚拟机监控程序也算）；“虚拟机平台”（Virtual Machine Platform，WSL 2 依靠它运行）已开启；WSL 已安装且不低于 2.1.5。这些信息由一次 PowerShell 查询取得。
2. **下载**：从 `https://desktop.docker.com/win/main/amd64/Docker Desktop Installer.exe` 下载，约 600 MB，放在 `Data\setup`。
   - 使用 Windows 的代理设置。
   - 断线后从断点续传；如果 Docker 中途发布了新版，就重新完整下载。
   - 下载完要核对数字签名：必须是 Docker Inc 签名且签名有效，否则删除，不会运行。
3. **开启 WSL 2（只在需要时）**：这是唯一需要管理员权限的一步，每台电脑只需一次。
   - 窗口外壳（`MainForm.cs` 的 `setup.enableWsl`）请 Windows 授权（用户账户控制），然后在一个命令行窗口里运行 Windows 自带的 `dism.exe`（开启虚拟机平台）和 `wsl.exe --install --no-distribution`；从微软商店下载失败时，改用 `--web-download` 从 GitHub 下载。
   - 之后要重启电脑。应用会在当前用户的 RunOnce 里登记一次，重启登录后自动打开，并按已保存的同意继续；也可以点“立即重启电脑”。
   - 是否已经重启过，不只看 Windows 报告“虚拟机平台已开启”（还没重启时它也可能这么报告），还看三件事：开启 WSL 之后有没有重新开机；Windows 是否还在等待重启（注册表 `Component Based Servicing\RebootPending`）；虚拟机监控程序是否已经在运行。
   - 虚拟机平台已开启、也重启过，但虚拟机监控程序仍没有运行（步骤 `hypervisor`）：多半是其他软件（例如部分安卓模拟器）关掉了 Windows 的虚拟化。应用会说明以管理员身份运行 `bcdedit /set hypervisorlaunchtype auto` 再重启。
4. **安装**：运行 `Docker Desktop Installer.exe install --user --quiet --accept-license --backend=wsl-2`，只为当前用户安装到 `%LOCALAPPDATA%\Programs\DockerDesktop`，不需要管理员权限。成功后删除安装包。
   - 数据存放位置不是默认位置时，再加 `--wsl-default-data-root=<数据位置>\Docker`：Docker 的 Linux 磁盘（浏览器组件和各环境的登录状态都在里面，会增长到几 GB）就放在数据旁边，而不是 C 盘。
   - 安装前按磁盘检查剩余空间：安装包约 0.5 GB、程序约 3 GB、Linux 磁盘起步约 2.5 GB，在同一个磁盘上的合计。
5. **启动并载入**：自动启动 Docker Desktop（找不到它的程序时改用 `docker desktop start`），等待就绪，再载入自带的浏览器组件。Docker Desktop 第一次启动时可能显示欢迎或登录窗口，可以跳过。

过程记录写在日志文件夹的 `backend.log` 里，以 `[docker-setup]` 开头。安装失败时，Docker 安装程序自身日志的末尾会附在 `Data\build.log`。同意时间和开启 WSL 的时间记在 `Data\setup\docker.json`。

应用能找到两种安装方式的 Docker Desktop：只为当前用户安装（`%LOCALAPPDATA%\Programs\DockerDesktop`，Docker Desktop 4.83 起的默认方式），以及为所有用户安装（`C:\Program Files\Docker\Docker`）。自定义了安装位置时，从 Docker Desktop 的卸载信息里读取。

已经装好的 Docker Desktop 启动不了时（比如重启后“虚拟机平台”仍未运行，Docker 会提示 “Virtual Machine Platform is not enabled”），应用也做同样的电脑检查，在“运行组件”里给出同样的步骤：开启 WSL 2、重启电脑、或修复虚拟化。这些步骤不需要再同意 Docker 的协议。

## 数据放在哪里

应用里“账号与资源 → 存储位置”列出下面这些位置和各自占用的空间（每个环境的登录状态与传输文件分开统计），每一处都有“打开”按钮。

| 内容 | 位置 |
| --- | --- |
| 数据库、订阅、账号记录、文件传输文件夹 | `<数据位置>\Data`，默认 `%LOCALAPPDATA%\BrowserWorkbench\Data` |
| 各环境的 Firefox 配置与登录状态、浏览器组件 | Docker 的 Linux 磁盘，存储卷 `workbench-<范围>-<环境编号>` |
| 日志 | `%LOCALAPPDATA%\BrowserWorkbench\Logs\backend.log` |
| 窗口自身的浏览数据（只有工作台页面） | `%LOCALAPPDATA%\BrowserWorkbench\WebView2` |

数据位置记在注册表 `HKCU\Software\BrowserWorkbench` 的 `DataLocation`（安装向导或移动数据时写入）；没有这一项时用默认位置。卸载不删除它，重新安装会找回原来的数据。日志和窗口自身的浏览数据很小，始终在默认位置。

**移动数据**：在“存储位置”里点“更改位置…”，选一个文件夹。
- 选的文件夹里已有其他文件时，数据放进其中新建的 `BrowserWorkbench` 文件夹。网络位置、程序文件夹里面、已经有一份工作台数据的地方、写不进去或空间不够的地方都会被拒绝，并说明原因。
- 确认后，窗口先停止运行中的环境和后台，再由 `workbench/relocate.py` 复制到新位置的 `Data.partial`，逐个文件核对大小和 SHA-256，全部一致才改名为 `Data`、记下新位置。原来的文件夹改名为“旧数据（已移到新位置，可以删除）”，确认新位置正常后，可以在“存储位置”里删除（会再次确认，删除后无法恢复）。任何一步出错，新位置的半成品会被删掉，原来的数据不动，工作台继续用原来的位置。
- Docker 存储卷的名字在第一次运行时记进数据库（`runtime_scope`，与旧版本按数据路径算出的值相同），所以移动后各环境仍然对应原来的登录状态。

**Docker 的 Linux 磁盘**由 Docker Desktop 管理（默认 `%LOCALAPPDATA%\Docker\wsl`，设置记在 `%APPDATA%\Docker\settings-store.json` 的 `CustomWslDistroDir`）。由应用安装 Docker Desktop、而数据位置不是默认时，它在 `<数据位置>\Docker`。要移动已有的磁盘：先停止所有环境，打开 Docker Desktop → Settings → Resources → Advanced，在 Disk image location 选新文件夹，再点 Apply & restart，登录状态会一起移过去。

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
- 后端在 Windows 上：用 `CREATE_NO_WINDOW` 启动 docker 命令（否则每次都会闪一个命令行窗口）；在只为当前用户和为所有用户安装的两个位置找 Docker Desktop（见上文）；数据文件夹用 `msvcrt.locking` 加锁防止两个后端同时使用；文件传输没有 `dir_fd`，改为逐级用 `lstat` 检查，拒绝符号链接和目录连接点。

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

2026-11-08 在 GitHub 提供的 Windows 机器（`windows-latest`，Windows Server 2025）上验证过的。工作流是 `.github/workflows/windows.yml`，在代码推到 `windows-check` 分支、且安装包已放进同版本的草稿发布时运行。最近一次（提交 5c3009d）全部通过：

- Windows 版 Python 3.12 上的基础测试 163 项通过。其中 12 项只检查 Mac 路径或导入旧版 Mac 数据，按设计跳过。
  - 第一次运行（2026-11-05）查出两个问题：Windows 没有系统时区库；读写文本文件默认不是 UTF-8。
  - 两个问题都已修复：依赖里加入了 `tzdata`，读写文本文件一律指定 UTF-8。
- 自动安装 Docker Desktop 的准备步骤（`tests/windows_setup_check.py`，不安装 Docker Desktop）：
  - 系统查询有结果：版本号 26100，虚拟化与虚拟机平台已开启，WSL 3.0.3；开机时间、两个 Docker Desktop 安装位置都能读到。
  - 签名核对：微软签名的记事本读作“Microsoft Windows”，不会被当成 Docker；未签名的文件被拒绝；从 Docker 官网实际下载的安装包（623,748,528 字节，用时 7 秒）签名有效，属于 Docker Inc。
  - 在 RunOnce 里登记“重启后打开”、再删除，都正常。
  - 前一次运行查出一个问题：检查从 PowerShell 7 里启动时，Windows PowerShell 继承了 PowerShell 7 的模块路径，找不到签名核对命令，下载好的安装包每次都被当作签名不符删掉。已修复：后端启动 Windows PowerShell 时不再传入这个路径。从 PowerShell 7 窗口打开应用的电脑原本也会遇到这个问题。
- 安装：从草稿发布下载安装包（SHA-256 与本地构建一致）并静默安装。程序文件和开始菜单快捷方式都已就位，自带的 Python 能读取时区。
- 自检：启动窗口，在 WebView2 里运行 `tests/ui/windows_smoke.js`，7 项全部通过：
  - 页面运行在 Windows 外壳里，原生桥可用；
  - 自带后端返回了正确的版本和平台；
  - 没有 Mac 标题栏占位，使用 Windows 的说法；
  - 剪贴板经原生桥往返，包括中文；
  - 拒绝在资源管理器里显示不是本应用保存的文件；
  - Docker 不可用时给出说明（这台机器装了 Docker 命令，但后台服务没有运行）；
  - 开启 WSL 2 的管理员步骤：以管理员身份运行 `dism.exe` 与 `wsl.exe --install`，15 秒后报告完成（GitHub 的机器不弹授权窗口）。

  数据目录用的是带空格的路径。
- 退出与卸载：自检后应用自行退出，后端也随之结束；静默卸载后程序文件被删除。

2026-11-09，v0.8.1（选择位置、移动数据、重启判断）在同样的机器上全部通过（运行 42579420893，提交 9e487ce）：

- Windows 版 Python 3.12 上的基础测试 188 项通过，12 项按设计跳过。电脑检查多读到两项：虚拟机监控程序正在运行，没有等待中的重启。
- 安装向导（`tests/windows_installer_pages.ps1`，像用户一样点击并给每一页截图）：两页都默认显示通常的位置；程序位置和数据位置都选已有别人文件的文件夹时，都会提示改用新建的子文件夹；数据页只显示可用空间。装好后程序在子文件夹里，注册表记下了带子文件夹的数据位置，开始菜单快捷方式指向新位置；卸载后别人的文件都还在，数据位置仍有记录。
  - 第一次运行查出一个问题：NSIS 在离开页面后会把输入框里的文字重新读回变量，所以安装程序提示的子文件夹被丢掉，程序装进了用户选的文件夹本身。已修复：确认子文件夹后，把它写回输入框。
- 静默安装到 D 盘上含空格和中文的程序、数据位置；窗口自检 11 项通过，包括“存储位置”给出的三个位置和截图、移动前的检查。随后真的移动了数据：新位置有数据库，旧文件夹改名为“旧数据（已移到新位置，可以删除）”保留，注册表指向新位置，后台从新位置重新启动，应用自行退出。
- 静默卸载后，数据仍在新位置。

这些机器不能运行 Linux 容器，也装不了 Docker Desktop，所以 Docker Desktop 的安装和浏览器环境本身还没有在 Windows 上运行过。

还需要在真实 Windows 电脑上验证的：

- 从 0.8.0 升级（已有数据时不再询问数据位置，数据不动）；SmartScreen 提示。
- 有浏览器环境时移动数据：环境先停止，移动后各环境仍是原来的登录状态。
- 由应用安装 Docker Desktop 到非默认数据位置旁边（`--wsl-default-data-root`）；开启 WSL 2 后的重启判断和“虚拟化没有运行”的提示。
- WebView2 窗口的其余原生功能：下载到电脑、在资源管理器中显示、系统菜单、深色标题栏、窗口位置记忆、再次打开回到已有窗口；以及退出时的询问。
- 自动安装 Docker Desktop 的完整过程：授权窗口、重启后自动打开并继续、Docker Desktop 的安装与首次启动；已装好的 Docker Desktop 的查找与启动。
- 在真实的 Docker Desktop（WSL 2）里载入组件、启动环境并显示画面。
- 文件传输文件夹在 Windows 共享下的读写。
- 用户名含中文或空格时，Docker 能否共享文件传输文件夹。
