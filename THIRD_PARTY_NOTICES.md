# 第三方组件

源码仓库只提交工作台自身的代码，以及“终端”标签用的 xterm.js（原样放在 `static/vendor/xterm/`）。**Mac 应用（DMG）和 Windows 安装包会随附**下列第三方组件的二进制文件：自带的 Python 运行时与依赖，以及预先构建的浏览器组件镜像；Windows 版另附 WebView2 SDK 组件与安装程序框架。第三方组件继续适用其原有许可证与商标规则。

## 随应用附带：本机后台服务

| 组件 | 用途 | 许可证 | 上游 |
| --- | --- | --- | --- |
| CPython 3.12（python-build-standalone 构建） | 运行工作台后端 | PSF License（构建脚本 BSD-3-Clause），内含 OpenSSL（Apache-2.0）、SQLite（公共领域）等 | https://www.python.org/ ・ https://github.com/astral-sh/python-build-standalone |
| xterm.js 6.0.0（@xterm/xterm）与 @xterm/addon-fit 0.11.0 | 环境“终端”标签里的命令行显示 | MIT，全文附在 `static/vendor/xterm/LICENSE.txt` | https://github.com/xtermjs/xterm.js |
| FastAPI / Starlette / Pydantic / Uvicorn / HTTPX / httpcore / h11 / anyio / websockets / PyYAML / certifi / tzdata 等 | 本机 HTTP 服务与依赖；tzdata 提供 IANA 时区数据（Windows 没有系统自带的一份） | MIT、BSD、MPL-2.0（certifi）、Apache-2.0（tzdata，其中的 IANA 时区数据属公有领域）等，详见各包 `*.dist-info` 中的许可文件 | PyPI 对应项目 |
| Anthropic Python SDK 2.3.0（anthropic）及其依赖 httpx2 / httpcore2 / truststore / jiter / docstring-parser / opentelemetry-api / sniffio 等 | “模型网关”通过 Anthropic 官方接口调用 Claude | Apache-2.0（anthropic、opentelemetry-api）、BSD-3-Clause（httpx2、httpcore2）、MIT（truststore、jiter、docstring-parser）等，详见各包 `*.dist-info` 中的许可文件 | https://github.com/anthropics/anthropic-sdk-python |

## 随 Windows 版附带

| 组件 | 用途 | 许可证 | 上游 |
| --- | --- | --- | --- |
| CPython 3.12 Windows 版（python-build-standalone 构建），含 Microsoft Visual C++ 运行库 `vcruntime140*.dll` | 运行工作台后端 | PSF License；VC++ 运行库按 Microsoft Visual Studio 可再发行组件条款随附 | 同上 |
| Microsoft Edge WebView2 SDK（`Microsoft.Web.WebView2.*.dll`、`WebView2Loader.dll`） | 窗口内显示工作台页面 | BSD 风格许可，全文随应用附在 `licenses\WebView2-SDK.txt` | https://www.nuget.org/packages/Microsoft.Web.WebView2 |
| Microsoft Edge WebView2 运行库安装器（`MicrosoftEdgeWebview2Setup.exe`，仅在缺少运行库时由安装程序运行） | 安装 WebView2 运行库 | Microsoft 分发条款 | https://developer.microsoft.com/microsoft-edge/webview2/ |
| NSIS 3.11 | 安装与卸载程序 | zlib/libpng 许可（部分组件 bzip2、CPL），全文附在 `licenses\NSIS.txt` | https://nsis.sourceforge.io/ |
| .NET Framework 4.8、Microsoft Edge WebView2 运行库 | 窗口外壳运行环境 | Windows 自带或由微软安装，不随应用附带 | https://dotnet.microsoft.com/ |

## 随应用附带：浏览器组件镜像（`runtime-image/browser-runtime.tar.gz`）

由本仓库 `runtime/Dockerfile` 从下列来源构建（Mac 版为 ARM64，Windows 版为 x64）；完整的包名与版本清单随应用附在 `runtime-image/manifest.txt`（Mac 版在 `Contents/Resources/` 下）。

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
| Docker Desktop / OrbStack / WSL 2 | 容器运行服务 | 由使用者自行安装，并遵守其适用条款；不随应用附带 |

此仓库和应用不附带第三方网站账号、代理订阅或访问权限。源码中的第三方名称用于说明兼容对象，不代表其认可本项目。

本项目自身未额外选择公开开源许可证；仓库拥有者可向他人提供使用授权。第三方组件的许可不因此改变。
