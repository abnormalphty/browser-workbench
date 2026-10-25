# 构建 DMG

需要：macOS 13+、Xcode（命令行工具中的 `swiftc`）、正在运行的 Docker（导出浏览器镜像时需要）、可访问 GitHub 和 PyPI 的网络（第一次下载 Python 运行时与依赖）。

```sh
# 1. 浏览器组件镜像：没有 local-browser-workbench:0.7.0 时会先构建（首次需要联网，十几分钟）
scripts/export_runtime_image.sh arm64

# 2. 组装并签名应用（带上镜像）
scripts/build_app.sh arm64 --with-image ~/Library/Caches/BrowserWorkbenchBuild/runtime-image/browser-runtime-arm64.tar.gz

# 3. 生成 DMG → dist/Browser-Workbench-0.7.2-arm64.dmg 及 .sha256
scripts/make_dmg.sh arm64
```

不带 `--with-image` 时生成轻量版应用：首次使用会在使用者电脑上联网构建镜像，与 v0.6.1 相同。

## 各步骤做了什么

- `fetch_python.sh`：下载 python-build-standalone 的 CPython 3.12.15（发布 20261003），按脚本内固定的 SHA-256 校验。
- `build_app.sh`：
  - 用 `swiftc` 编译 `macos/Sources`（最低 macOS 13），生成 Info.plist 和图标（`macos/make_icon.swift`）。
  - 复制 Python，按 `requirements.txt` 只安装预编译 wheel；删去 pip、tkinter、测试和带本机路径的命令行包装脚本。
  - 按白名单复制 `workbench/`、`static/`、`runtime/`；预编译 `.pyc`（unchecked-hash），运行时以 `-B` 启动，从不写入已签名的应用包。
  - 运行 `scripts/check_bundle.py`：应用包里出现数据库、日志、launch.json、proxy.yaml、浏览器配置目录、私钥或构建者本机路径时，构建失败。
  - 对每个 Mach-O 文件和整个应用做 ad-hoc 签名（`SIGN_IDENTITY` 可换成 Developer ID 证书），最后 `codesign --verify --deep --strict`。
- `export_runtime_image.sh`：检查镜像架构与 `workbench.runtime` 标签，生成组件清单（Firefox、mihomo、全部 Debian 包版本），`docker save | gzip` 导出并写 SHA-256。
- `make_dmg.sh`：应用 + “应用程序”快捷方式 + 安装说明，`hdiutil` 生成 UDZO 压缩的 DMG 并校验。

构建产物在 `~/Library/Caches/BrowserWorkbenchBuild`（可用 `BUILD_ROOT` 改位置）。只有 DMG 放进项目的 `dist/`。原因：项目在 iCloud 同步的“文稿”里，大文件会被上传；iCloud 附加的 Finder 信息也会让 codesign 拒绝签名。

## 版本号

- 应用版本：`workbench/__init__.py` 的 `__version__`（Info.plist、DMG 文件名、界面都从这里取）。
- 浏览器组件版本：`workbench/runtime.py` 的 `RUNTIME_VERSION`，与 `runtime/Dockerfile` 的 `workbench.runtime` 标签保持一致。只要 `runtime/` 下的文件有改动就要一起提高，否则已安装的旧镜像会被当成新镜像继续使用。

## 签名与公证

当前没有 Apple 开发者证书，只能 ad-hoc 签名：在自己电脑上构建的应用可直接打开；从网上、微信、AirDrop 收到的 DMG，首次打开需要到“系统设置 → 隐私与安全性”点“仍要打开”。

如果以后加入 Apple Developer Program（个人 99 美元/年）：

1. 用 `SIGN_IDENTITY="Developer ID Application: …"` 运行 `build_app.sh`，并为签名加上 `--options runtime --timestamp`（脚本里注明的位置）。
2. 自带的 Python 扩展模块需要用同一证书签名；如遇库校验问题，再评估 `com.apple.security.cs.disable-library-validation` 等授权。
3. `xcrun notarytool submit dist/….dmg --wait`，然后 `xcrun stapler staple`。

这一部分尚未实际做过，需要有证书后再验证。

## Intel Mac

`fetch_python.sh x86_64` 和 `build_app.sh x86_64` 可以在 Apple 芯片的 Mac 上交叉生成 Intel 版外壳与 Python 依赖，但浏览器镜像要在 Intel Mac 上导出（`export_runtime_image.sh` 只导出本机架构）。Intel 版目前没有构建和验证。
