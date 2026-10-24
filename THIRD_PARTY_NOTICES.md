# 第三方组件

源码仓库只提交工作台自身的代码。**Mac 应用（DMG）会随附**下列第三方组件的二进制文件：自带的 Python 运行时与依赖，以及预先构建的浏览器组件镜像。第三方组件继续适用其原有许可证与商标规则。

## 随应用附带：本机后台服务

| 组件 | 用途 | 许可证 | 上游 |
| --- | --- | --- | --- |
| CPython 3.12（python-build-standalone 构建） | 运行工作台后端 | PSF License（构建脚本 BSD-3-Clause），内含 OpenSSL（Apache-2.0）、SQLite（公共领域）等 | https://www.python.org/ ・ https://github.com/astral-sh/python-build-standalone |
| FastAPI / Starlette / Pydantic / Uvicorn / HTTPX / httpcore / h11 / anyio / websockets / PyYAML / certifi 等 | 本机 HTTP 服务与依赖 | MIT、BSD、MPL-2.0（certifi）等，详见各包 `*.dist-info` 中的许可文件 | PyPI 对应项目 |

## 随应用附带：浏览器组件镜像（`runtime-image/browser-runtime.tar.gz`）

由本仓库 `runtime/Dockerfile` 从下列来源构建；完整的包名与版本清单随应用附在 `Contents/Resources/runtime-image/manifest.txt`。

| 组件 | 用途 | 许可证 | 源码 |
| --- | --- | --- | --- |
| Firefox ESR（Debian 软件包） | 标准浏览器 | MPL-2.0 | https://www.mozilla.org/firefox/enterprise/ ・ Debian 源码包 firefox-esr |
| mihomo | 环境内代理 | GPL-3.0 | https://github.com/MetaCubeX/mihomo （对应 Dockerfile 中固定的版本标签） |
| noVNC / websockify | 网页中的桌面画面 | MPL-2.0 / LGPL-3.0 | https://github.com/novnc/noVNC ・ https://github.com/novnc/websockify |
| Xvfb / x11vnc / Openbox / xdotool / xclip 等 | Linux 虚拟桌面 | MIT/X11、GPL-2.0 等 | Debian 对应源码包 |
| Debian 12 基础系统、Python 3.11 官方镜像 | 容器系统 | 各软件包自身许可（见 `/usr/share/doc/*/copyright`） | https://www.debian.org/ ・ https://hub.docker.com/_/python |

GPL / LGPL 组件的对应源码可从上面列出的上游取得：Debian 软件包可用 `apt-get source <包名>=<版本>` 按清单中的版本获取，mihomo 对应 Dockerfile 中固定的发布标签。如需对应源码而无法从上游获得，可通过本仓库的 Issues 联系维护者。

## 其他

| 组件 | 用途 | 上游 |
| --- | --- | --- |
| Natural Earth | 世界地图底图 | https://www.naturalearthdata.com/about/terms-of-use/ （公共领域数据） |
| Docker Desktop / OrbStack | 容器运行服务 | 由使用者自行安装，并遵守其适用条款；不随应用附带 |

此仓库和应用不附带第三方网站账号、代理订阅或访问权限。源码中的第三方名称用于说明兼容对象，不代表其认可本项目。

本项目自身未额外选择公开开源许可证；仓库拥有者可向他人提供使用授权。第三方组件的许可不因此改变。
