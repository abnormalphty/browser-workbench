# 验证范围

自动测试使用临时数据和模拟节点，不需要个人订阅或网站账号。基础测试覆盖订阅、存储、认证、防跨站操作、代理配置、文件传输、地理与时区、账号提示识别、资源额度和暂停安全边界。

容器集成测试需要本机 Docker 和已准备的镜像，使用独立 scope 的测试环境与本地网页；输出写入被忽略的 `verification-data/`。它们不会验证个人 Claude 账号是否可登录，也不承诺任意线路都可用。

源码发布前会重新执行基础测试和源码隐私检查；原工作台已有实际浏览器的启动 / 停止、存储隔离、代理中断不直连、时区、双向剪贴板与文件传输验收。本分享目录不包含原工作台日志、截图或实际账号检测记录。


分享版发布验收（2026-10-22）：全新 Python 虚拟环境安装依赖成功；72项基础测试通过；空工作台为零账号 / 零节点；从本 Dockerfile 实际构建 ARM64 镜像成功。新镜像的7项浏览器运行 / 时区 / 代理 / 存储检查、5项真实剪贴板 / 上传下载 / 停止后文件保留检查均通过。测试只使用临时数据，未使用实际订阅或 Claude 登录。隐私检查和独立只读审查未发现阻断问题。


v0.6.1 准备流程回归：76项自动检查通过，包含模拟 Docker 未启动→等待→准备组件、已有镜像复用、未安装提示和等待超时。真实已启动的Docker和已有镜像验证复用成功，镜像ID未改变，未打开或重建任何用户环境。Docker未启动场景使用模拟回归，未为测试关闭用户Docker。朋友的具体代理/镜像源/资源配置问题尚未取得，不能据此声称其问题已经解决。


## v0.8 Windows 版

- 在 Mac 上：基础测试含 Windows 分支；窗口外壳编译；安装包内容核对；x64 浏览器组件载入后在模拟环境里按 Windows 的存储方式跑容器集成 7 项与文件传输 5 项（结果与方法见 [Windows 版说明](WINDOWS.md#验证状况)）。
- 模拟运行的容器测试：先用应用的载入流程把 `browser-runtime-x86_64.tar.gz` 载入为 `local-browser-workbench:<版本>`（会暂时替换本机同名的 Mac 镜像，测完删掉，再由 Mac 应用自己载入），设 `WORKBENCH_PROFILE_STORAGE=volume` 运行两个集成测试，并把页面检查的等待时间放宽到 2 分钟左右。
- 在 Windows 上：
  - GitHub 的 Windows 机器（`.github/workflows/windows.yml`）2026-11-08 全部通过，包括单元测试，以及静默安装、窗口自检、退出、卸载（见 [Windows 版说明](WINDOWS.md#验证状况)）。
  - 自动安装 Docker Desktop 的真实 Windows 检查（`tests/windows_setup_check.py`）：
    - 查询系统状态；
    - 签名检查从 PowerShell 7 里启动也能运行（GitHub 的检查步骤就在 PowerShell 7 里）；
    - 确认微软签名的程序和未签名的文件都会被拒绝；
    - 写入并删除 RunOnce；
    - 实际下载 Docker 安装包并核对 Docker Inc 的签名。

    窗口自检还会跑一次需要管理员权限的 WSL 2 步骤（GitHub 的机器不会弹出授权窗口）。这些机器装不了 Docker Desktop，所以安装本身只在真机上验证。2026-11-08 全部通过；前一次运行查出签名检查在 PowerShell 7 里启动时不能运行，已修复。
  - v0.8.1 起还检查位置（`tests/windows_installer_pages.ps1` 与 `tests/ui/windows_smoke.js`）：
    - 像用户一样点过安装向导：程序位置和数据位置都选已有别人文件的文件夹，确认会改用新建的子文件夹，并给每一页截图；装好后核对程序、注册表里的数据位置和开始菜单快捷方式；卸载后核对别人的文件都还在、数据位置仍有记录。
    - 静默安装到含空格和中文的程序、数据位置；窗口自检核对“存储位置”给出的路径并截图，最后真的把数据移到另一个文件夹：新位置有数据库，旧文件夹改名保留，注册表更新，后台从新位置重新启动。
    - 卸载后数据仍在新位置。
  - 真机验收（Docker Desktop 与真实环境）尚未进行。

## v0.7 Mac 应用

- 基础测试：`.venv/bin/python -m unittest discover -s tests`（187 项，含 `tests/test_windows.py` 与 `tests/test_docker_setup.py`（在任何电脑上按 Windows 分支运行；后者用本机的测试下载服务验证断点续传、签名不符时删除、需要开启 WSL 或重启时停下等待）、`tests/test_desktop.py`、`tests/test_migrate.py`、`tests/test_storage.py`（存储位置、移动数据的检查与核对）；在 Windows 上运行时跳过只检查 Mac 路径的 Docker 查找测试和旧版数据导入测试）。
- 出口自动检测：单元测试覆盖哪些线路会被自动检测、失败后的重试间隔、两个查询服务的回答解析和中文城市名；`tests/integration_runtime.py` 之外，另用真实浏览器镜像跑过一次连不上的线路（约 10 秒结束，记录失败并保留名称推测）。
- 容器集成：`tests/integration_runtime.py`（7 项）与 `tests/integration_transfers.py`（5 项），需要已有与 `RUNTIME_VERSION` 同版本的 `local-browser-workbench` 镜像；设 `WORKBENCH_PROFILE_STORAGE=volume` 可按 Windows 的方式（登录数据放在 Docker 存储卷）再跑一遍。
- 端到端：`tests/ui/run_app_smoke.sh "<路径>/Browser Workbench.app"`。用 `open -g` 在后台启动应用（不抢键盘），数据目录用临时文件夹（路径含空格），通过开发者变量 `BROWSER_WORKBENCH_UI_TEST` 在应用窗口内运行 `tests/ui/app_smoke.js`，并把截图写到运行目录。检查：原生桥接、标题栏那条带能拖动窗口（点击交给原生拖动层，带下方的按钮仍可点击，页面缩放后同样成立，双击按系统设置缩放；用模拟点击检查，不会真的移动窗口）、环境设置里显示线路的时区与当前是夏令时还是冬令时、自动连上 Docker 与（必要时）载入自带镜像、无 Docker 时的指引显示、Mac 剪贴板→远程网页→Mac 剪贴板、在画面上投放文件（模拟事件）、Firefox 下载经“下载到电脑”逐字节一致、退出时停止环境且应用与后台都退出。运行期间会临时占用 Mac 剪贴板，结束后恢复其中的文字。
- 不在自动测试范围：真实订阅与 Claude 登录、真人拖放与系统文件面板、退出询问框的按钮、注销 / 关机时的自动停止、全新安装 Docker Desktop、从网上下载后的 Gatekeeper 流程、Intel Mac。
- 界面截图：`tests/ui/run_screens.sh "<路径>/Browser Workbench.app"`，假数据见 `tests/ui/seed_demo.py`（服务器均为 `*.example.invalid`）。
