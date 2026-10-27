shortcut 原生桌面组件

用途
shortcut_app/desktop_manager.py 将共用分类结果传给 shortcut_app/native_desktop_host.py。
连接进程通过本地管道接收路径，DLL 在 Explorer 现有桌面视图中收起或恢复项目。
不移动文件，不更改文件隐藏属性，不绘制替代桌面。
桌面图标、字体、右键菜单和拖放仍由 Explorer 处理。

构建
需要 Visual Studio 2022 Build Tools 的 C++ 桌面开发组件（MSVC x64 + Windows SDK）。
在仓库根目录执行：
powershell -NoProfile -ExecutionPolicy Bypass -File .\native_desktop\build.ps1

也可显式指定 LLVM-MinGW 的 clang++.exe；本次已用 20261020 UCRT x64 工具链验证：
.\native_desktop\build.ps1 -CompilerPath '工具链路径\bin\clang++.exe'
.\tests\run_native_tests.ps1 -CompilerPath '工具链路径\bin\clang++.exe'
指定工具链时不依赖系统 MSVC 安装，也不会在编译失败后改用其他编译器。

默认在本目录输出 ShortcutDesktop.dll 和 ShortcutShell.dll，使用静态 C++ 运行库。
packaging/shortcut.spec 会把两个 DLL 放到打包资源的 native_desktop 子目录。
不要提交 obj、lib、exp、dll 等本机构建产物。

职责
bridge.cpp：启动时用 WH_GETMESSAGE 线程钩子连接 Explorer 桌面线程，完成后解除启动钩子。
filter.cpp：使用原 IShellView / IShellFolderView 收纳和恢复项目，维护退出时的恢复流程。
recycle.cpp：在 Shortcut 后台 STA 使用 IFileOperation 回收项目，不在 Explorer 回调内操作文件。
shell_menu.cpp：独立 ShortcutShell.dll，通过 IContextMenu/2/3 构造原文件的 Windows 经典菜单，
转发扩展菜单消息并执行用户选中的命令；不向 Explorer 注入这部分代码。
PreDeleteItem 拒绝非回收操作，没有永久删除重试；清空回收站使用系统确认。

事件与生命周期
分类结果变化时更新；Shell 事件在短时间内合并，不进行高频扫描。
每次处理需要遍历桌面顶层视图，不代表逐个事件都能直接定位唯一项目。
正常断开、主进程或连接进程退出时恢复桌面项目。
DLL 直接等待主进程和连接进程的内核句柄；主进程崩溃或整个 Shortcut 进程树被终止，
无需依赖 Python 退出钩子或仍在响应的连接进程。托管使用逐项收纳，不关闭桌面图标总开关。
退出恢复遇到 Shell 嵌套回调或短暂无响应时继续延迟重试，直到恢复完成再卸载 DLL；
该重试只发生在退出恢复期间，不增加正常空闲轮询。Explorer 永久无响应时无法即时恢复。
首次收到并成功应用完整的分类路径后才报告就绪，连接期间已缓冲消息也会主动读取。
Explorer 退出通过内核事件感知；重连最多 20 次，间隔 500 ms，初次连接最多等待 8 秒。
启动连接失败时尝试恢复原生桌面并提示，不无限重试连接。

隔离回归验证（不连接 Explorer、不改变真实桌面）
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\run_native_tests.ps1
原生测试直接编译实际 bridge.cpp，将进程等待和窗口消息替换为模拟函数，
覆盖主进程退出、辅助进程退出、超时后延迟恢复和恢复消息回调退出屏障。
另有 shell_menu.cpp 测试：为测试临时快捷方式实际构建 Windows 菜单，但替换显示为取消，
从不执行快捷方式或请求提权；命令索引与 IContextMenu3 消息转发使用模拟对象验证。

已验证与限制
已在 Windows 11 x64 的真实 Explorer 桌面完成连接、收纳、文件变化、
正常退出及连接进程意外退出后的恢复验证。
IShellFolderView 是旧接口，微软文档已标记不再可用，当前系统可获取并不代表跨版本保证。
完整 Explorer 重启、多显示器、运行中切换 DPI、多个桌面管理器共存尚未完整验证。
旧实验与含本机路径的诊断记录不在公开仓库中。

接口资料
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexw
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nn-shlobj_core-ishellfolderview
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-ishellfolderview-removeobject
https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags
https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-predeleteitem
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shchangenotifyregister
