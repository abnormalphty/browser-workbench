# 第三方组件

本仓库提供工作台源码；浏览器和桌面运行组件由 Dockerfile 从各自的软件源安装，不随仓库提交二进制文件。第三方组件继续适用其原有许可证与商标规则。

| 组件 | 用途 | 上游 |
| --- | --- | --- |
| Firefox ESR | 标准浏览器 | https://www.mozilla.org/firefox/enterprise/ |
| mihomo | 环境内代理 | https://github.com/MetaCubeX/mihomo |
| noVNC / websockify | 网页中的桌面画面 | https://github.com/novnc/noVNC / https://github.com/novnc/websockify |
| Xvfb / x11vnc / Openbox | Linux 虚拟桌面 | Debian 软件源提供 |
| Python / FastAPI / Uvicorn / HTTPX / PyYAML / websockets | 本机服务与容器服务 | 对应官方项目、PyPI 与发行包的许可文件 |
| Natural Earth | 世界地图底图 | https://www.naturalearthdata.com/about/terms-of-use/ （公共领域数据） |

Docker Desktop 由使用者自行安装并遵守其适用条款。此仓库不附带第三方网站账号、代理订阅或访问权限。源码中的第三方名称用于说明兼容对象，不代表其认可本项目。

本次分享未额外选择公开开源许可证；仓库拥有者可向受邀成员提供使用授权。第三方组件的许可不因此改变。
