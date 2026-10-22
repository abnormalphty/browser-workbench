# 安装排查

## Python 版本不够

需要 Python 3.11+。在终端执行 `python3 --version` 检查。若装了多个版本，可先用 `python3.11 launch.py` 等明确版本命令启动。

## Docker 尚未就绪

先打开 Docker Desktop，等待引擎就绪，再回面板重试。macOS 已安装但命令不在 PATH 时，工作台也会检查标准的 Docker 应用路径。

## 镜像准备失败

检查网络是否能访问 Docker Hub、Debian、PyPI 和 GitHub release。不要关闭证书验证。详情在自己的 `data/build.log`；分享日志前先检查其中的个人目录与网页内容。

Dockerfile 默认从 Debian 软件源安装 Firefox ESR，因此实际小版本会随软件源更新。不是所有构建日期都得到同一个浏览器版本。

## 提示资源不足

电脑物理内存和 Docker Desktop 分配内存是两个值。工作台按 Docker 可用容量限制环境的内存额度合计，并预留512MB。可以降低环境额度或停止不用的环境；调整 Docker Desktop 容量应按自己的电脑情况进行。

## 启动后网页不显示

本机地址默认是 http://127.0.0.1:8766。该端口被其他应用占用时，双击入口会提示冲突。可用 `python3 run.py --port 8768` 启动其他端口，但双击入口仍只管理默认端口。

## 更新源码

保留自己原来的 `data/`。替换源码并重启面板；重新构建镜像后，正常停止并重新打开环境才加载新组件。不要运行会删除绑定 profile 的清理命令。
