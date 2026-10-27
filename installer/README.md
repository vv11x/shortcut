# Windows 安装包

`shortcut.iss` 使用 Inno Setup 7 构建 x64 当前用户安装器。程序默认安装到 `%LOCALAPPDATA%\Programs\shortcut`，并在开始菜单创建启动与桌面图标恢复入口；桌面快捷方式由安装向导选项控制。

## 构建

先按照根目录 README 在工程外构建 `F:\shortcut-output\dist\shortcut\`，再安装 [Inno Setup](https://jrsoftware.org/isinfo.php)，并在 PowerShell 中执行：

```powershell
.\installer\build.ps1
```

若 `ISCC.exe` 不在 `PATH`，将其完整路径传给脚本：

```powershell
.\installer\build.ps1 -CompilerPath "C:\Program Files\Inno Setup 7\ISCC.exe"
```

默认生成 `F:\shortcut-output\dist\shortcut-v1.1.41.exe`，构建产物及其第三方运行库均保留在源码目录之外。也可以通过 `-DistributionDirectory` 和 `-OutputDirectory` 指定其他外部目录。

安装包包含应用及其随包 DLL、图标和许可文件。卸载程序目录时会保留 `%USERPROFILE%\.shortcut` 中的用户设置。
