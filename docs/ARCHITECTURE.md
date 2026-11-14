# 架构

FastAPI 面板由 Mac 应用的原生窗口（v0.7 起）或本机浏览器（源码运行）打开；每个环境对应独立 Docker 容器和绑定的持久 profile。容器包含标准 Firefox、mihomo、Xvfb、Openbox、x11vnc、noVNC 和受令牌保护的 worker。Mac 应用的组成与取舍见 [DESKTOP.md](DESKTOP.md)。

- `macos/`：Swift 原生外壳（窗口、菜单、退出流程、剪贴板 / 下载 / 文件选择桥接、旧版数据导入）。
- `workbench/desktop.py`：应用启动的后台入口（随机回环端口、就绪信号、单实例锁、随应用退出）。
- `workbench/docker_env.py`：在 Docker Desktop / OrbStack / Homebrew 位置查找 docker 命令。
- `workbench/migrate.py`：只读复制旧版 `data/` 到应用数据目录。
- `scripts/`：下载 Python 运行时、导出浏览器镜像、组装签名应用、生成 DMG、隐私检查。

- `launch.py` / `run.py`：本机启动入口，默认监听 127.0.0.1:8766。
- `workbench/store.py`：SQLite 环境、订阅、账号记录和额度；新安装为空数据库。
- `workbench/subscriptions.py`：解析并验证订阅节点。
- `workbench/runtime.py` / `resources.py`：仅管理本数据目录 scope 对应的容器，采样、启动 / 停止、暂停 / 唤醒及资源额度。
- `workbench/geography.py`：节点地区、出口检测、IANA 时区。
- `workbench/accounts.py` / `runtime/account_info.py`：用户主动执行的有限账号提示核对。
- `workbench/transfers.py`：受保护的文件传输。
- `workbench/terminal.py`：“终端”标签：`docker exec` 在环境里起一个小桥接程序（伪终端 + bash，以 browser 用户运行），页面经 WebSocket 收发；只接受工作台页面自己的连接。
- `workbench/gateway.py` / `openai_compat.py`：模型网关：127.0.0.1 上单独的端口，用官方 SDK 把 Messages 请求原样转给 Anthropic，把 OpenAI 格式的请求换成 Messages；API 密钥、专属密钥、设置历史与用量存在 SQLite 的设置表里。
- `static/`：本机界面（`app.js`，模型网关页在 `gateway.js`）、世界地图与剪贴板桥接；`static/vendor/xterm/` 是原样附带的 xterm.js。
- `runtime/`：容器构建与桌面进程，不使用浏览器调试连接。

本机面板、Docker 浏览器环境、Claude 云端代码执行环境是三个不同位置。云端回复中的 `/home/claude/...` 不是本机路径；通过网页下载后才进入环境的共享下载目录。
