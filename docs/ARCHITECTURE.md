# 架构

本机浏览器打开 FastAPI 面板；每个环境对应独立 Docker 容器和绑定的持久 profile。容器包含标准 Firefox、mihomo、Xvfb、Openbox、x11vnc、noVNC 和受令牌保护的 worker。

- `launch.py` / `run.py`：本机启动入口，默认监听 127.0.0.1:8766。
- `workbench/store.py`：SQLite 环境、订阅、账号记录和额度；新安装为空数据库。
- `workbench/subscriptions.py`：解析并验证订阅节点。
- `workbench/runtime.py` / `resources.py`：仅管理本数据目录 scope 对应的容器，采样、启动 / 停止、暂停 / 唤醒及资源额度。
- `workbench/geography.py`：节点地区、出口检测、IANA 时区。
- `workbench/accounts.py` / `runtime/account_info.py`：用户主动执行的有限账号提示核对。
- `workbench/transfers.py`：受保护的文件传输。
- `static/`：本机界面、世界地图与剪贴板桥接。
- `runtime/`：容器构建与桌面进程，不使用浏览器调试连接。

本机面板、Docker 浏览器环境、Claude 云端代码执行环境是三个不同位置。云端回复中的 `/home/claude/...` 不是本机路径；通过网页下载后才进入环境的共享下载目录。
