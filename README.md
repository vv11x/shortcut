# shortcut

Windows 11 桌面 Dock：分类、排序、搜索并打开快捷方式。分类只保存本机归属，不会自动移动原文件。

## 功能

- Dock 可停靠四边，或将分类显示为桌面分类盒。
- 自定义分类和规则，支持手动归类、拖放、排序、固定入口与搜索。
- 支持大图标和列表视图、深浅主题、系统托盘和回收站。
- 隐藏桌面图标时由独立进程监视；异常退出后自动恢复。若需手动恢复，退出 shortcut 后运行 `shortcut.exe --restore-desktop`。
- 文件复制、剪切、移入回收站；压缩和解压使用用户选择的 7-Zip 命令行程序。

## 安装

从 [Releases](https://github.com/vv11x/shortcut/releases) 下载 `shortcut-1.0.0.exe` 并运行。安装包自带运行环境。

压缩和解压需要单独安装 7-Zip，并在 shortcut 设置中选择 `7z.exe`。
手动修复入口也会安装到开始菜单的 shortcut 文件夹，名称为“恢复桌面图标”。

## 开发

需要 Python 3.13 x64。在 PowerShell 中运行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m shortcut
```

构建安装包还需要安装 Inno Setup 7，并运行 `build.ps1`。输出为 `dist/release/shortcut-1.0.0.exe`。

## 品牌素材

角色立绘和三视图位于 [`assets/branding`](assets/branding)，三视图可供用户参考和二创。64 张分类图标位于 [`assets/icons/shortcut-moe-v1`](assets/icons/shortcut-moe-v1)。素材来源记录见 [`assets/ASSET_SOURCES.md`](assets/ASSET_SOURCES.md)。

程序代码采用 MIT 许可。PySide6、Qt 和其他依赖适用其各自许可，见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 与安装包内的许可文件。
