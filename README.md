# shortcut

Windows 桌面快捷方式管理工具。支持分类规则、手动归类、四边快捷栏、桌面分类盒、搜索、高 DPI 绘制及原生桌面图标收纳。

本目录是独立工程，包含源码、资源、测试和本项目的原生组件。不包含 Python／Qt 第三方运行库、虚拟环境、旧构建产物或版本控制历史。运行依赖安装在工程目录之外。

## 启动

当前工程路径：`F:\work\shortcut`。

```powershell
cd F:\work\shortcut
python -B shortcut.py
```

也可以双击 `shortcut.cmd`。当前机器已安装的系统 Python 可直接运行；关闭程序使用托盘“退出”，或执行：

```powershell
python -B shortcut.py --stop
```

运行依赖见 `requirements.txt`。如需创建独立运行环境，请放到工程外，例如 `C:\ShortcutRuntime`：

```powershell
python -m venv C:\ShortcutRuntime
& C:\ShortcutRuntime\Scripts\python.exe -m pip install -r requirements.txt
& C:\ShortcutRuntime\Scripts\python.exe -B shortcut.py
```

## 使用

- 托盘“偏好设置”可切换快捷栏／桌面分类盒、停靠方向、主题、图标大小及桌面图标模式。
- 点击分类查看完整内容；分类面板支持单击或双击打开、Ctrl／Shift 多选、键盘 Enter 和 Esc。
- 搜索覆盖现有分类及固定入口。竖向按钮居中位于主栏上方，横向按钮紧邻可见主栏，间隔 8 个逻辑像素。
- 分类管理先修改草稿，保存才生效。从偏好设置打开时使用模态子窗口，设置不会遮挡分类管理。
- 拖入文件只修改虚拟归属，不移动原文件。复制、剪切、回收及外壳菜单操作原入口。
- 桌面盒默认 4×4 缩略图，完整分类数量不限；支持独立拖动、分页、虚拟归类和自定义图标。
- 隐藏当前界面或正常退出会恢复原生桌面图标；重新显示时应用已选模式。桌面盒模式保留原生回收站。
- 品牌图保留 512 像素原图，按实际屏幕像素绘制，避免悬停及高 DPI 下重复放大造成模糊。

配置位于 `%USERPROFILE%\.shortcut\config.json`，日志为同目录 `shortcut.log`。当前工程只使用现有名称及配置键，不再读取历史品牌标识。现有 `.shortcut` 配置继续保留使用。

## 目录

| 目录 | 用途 |
| --- | --- |
| `shortcut_app/` | 界面、分类、搜索、文件操作及桌面接入 |
| `assets/` | 应用 ICO、分类图标和角色资源 |
| `native_desktop/` | 原生组件源码、构建脚本和本项目 DLL |
| `tests/` | 自动化检查；`manual/` 为显式执行的 Windows 回归 |
| `packaging/` | 可选的可执行程序打包配置 |
| `installer/` | 可选的安装器脚本 |
| `docs/` | 图标、角色和验证说明 |

## 验证

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/manual/smoke_dialogs.py
python -B tests/manual/smoke_search.py
python -B tests/manual/smoke_transitions.py
```

实机测试会短暂显示界面或收纳桌面图标，并在结束后恢复；请先正常退出正在运行的程序。临时文件写到系统临时目录，见 [验证说明](docs/SETTINGS_AUDIT.md)。

## 构建

当前原生组件已可使用。修改 C++ 后，可使用 MSVC x64 与 Windows SDK 构建，或显式指定工程外的 LLVM-MinGW 编译器：

```powershell
.\native_desktop\build.ps1
.\native_desktop\build.ps1 -CompilerPath 'C:\Tools\llvm-mingw\bin\clang++.exe'
```

如需打包，请使用工程外的构建环境和输出目录，避免第三方库重新进入当前源码目录：

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --distpath F:\shortcut-output\dist --workpath F:\shortcut-output\build packaging/shortcut.spec
```

分发程序时应保留完整的 `F:\shortcut-output\dist\shortcut` 目录。打包产物会包含运行依赖，应与当前源码工程分开放置。

## 资源与许可

图标说明见 [图标资源](docs/ICONS.md)，角色设定见 [角色说明](docs/CHARACTER_GUIDE.md)。项目源自 WKaleXD／WWQ 的公开项目，保留原作者版权声明及 MIT 许可，详见 [LICENSE](LICENSE) 与 [第三方说明](THIRD_PARTY_NOTICES.md)。

目前已在 Windows 11 x64 验证。多屏热插拔、完整 Explorer 重启及真实开机登录仍需独立实机覆盖。
