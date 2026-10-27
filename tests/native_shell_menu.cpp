// Real Shell menu construction for temporary shortcuts; never show or execute it.
#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <wrl/client.h>
#include <cassert>
#include <iostream>
#include <string>

namespace {
    unsigned menus = 0;
    BOOL WINAPI HiddenShowWindow(HWND, int) { return TRUE; }
    BOOL WINAPI HiddenSetForegroundWindow(HWND) { return TRUE; }
    BOOL WINAPI CancelPopup(HMENU menu, UINT flags, int, int, HWND, LPTPMPARAMS) {
        assert(flags & TPM_RETURNCMD);
        assert(GetMenuItemCount(menu) > 0);
        ++menus;
        return 0;
    }
}
#define ShowWindow HiddenShowWindow
#define SetForegroundWindow HiddenSetForegroundWindow
#define TrackPopupMenuEx CancelPopup
#include "../native_desktop/shell_menu.cpp"

struct RecordingContext : IContextMenu3 {
    ULONG references = 1;
    unsigned invocations = 0, messages = 0;
    CMINVOKECOMMANDINFOEX received{};
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        *out = nullptr;
        if (iid == IID_IUnknown || iid == IID_IContextMenu || iid == IID_IContextMenu2 || iid == IID_IContextMenu3) {
            *out = static_cast<IContextMenu3*>(this); AddRef(); return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override { return --references; }
    HRESULT STDMETHODCALLTYPE QueryContextMenu(HMENU, UINT, UINT, UINT, UINT) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE GetCommandString(UINT_PTR, UINT, UINT*, LPSTR, UINT) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE InvokeCommand(CMINVOKECOMMANDINFO* command) override {
        assert(command->cbSize == sizeof(received));
        received = *reinterpret_cast<CMINVOKECOMMANDINFOEX*>(command);
        ++invocations;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE HandleMenuMsg(UINT, WPARAM, LPARAM) override { ++messages; return S_OK; }
    HRESULT STDMETHODCALLTYPE HandleMenuMsg2(UINT, WPARAM, LPARAM, LRESULT* result) override {
        ++messages; *result = 777; return S_OK;
    }
};

static void createLink(const std::wstring& path) {
    ComPtr<IShellLinkW> link;
    HRESULT hr = CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&link));
    assert(SUCCEEDED(hr));
    wchar_t system[MAX_PATH]{};
    assert(GetSystemDirectoryW(system, MAX_PATH));
    std::wstring target = std::wstring(system) + L"\\notepad.exe";
    assert(SUCCEEDED(link->SetPath(target.c_str())));
    assert(SUCCEEDED(link->SetArguments(L"--not-executed-by-regression-test")));
    assert(SUCCEEDED(link->SetWorkingDirectory(system)));
    ComPtr<IPersistFile> file;
    assert(SUCCEEDED(link.As(&file)));
    assert(SUCCEEDED(file->Save(path.c_str(), TRUE)));
}

static std::wstring payload(const std::wstring& first, const std::wstring& second = L"") {
    std::wstring result = first;
    result.push_back(L'\0');
    if (!second.empty()) { result += second; result.push_back(L'\0'); }
    result.push_back(L'\0');
    return result;
}

int main() {
    assert(ShowShellContextMenu(nullptr, nullptr, 0, 0, 0) == E_INVALIDARG);
    assert(ShowShellContextMenu(nullptr, L"missing terminator", 5, 0, 0) == E_INVALIDARG);
    assert(SUCCEEDED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED)));
    wchar_t temp[MAX_PATH]{}, name[MAX_PATH]{};
    assert(GetTempPathW(MAX_PATH, temp));
    assert(GetTempFileNameW(temp, L"wds", 0, name));
    assert(DeleteFileW(name));
    assert(CreateDirectoryW(name, nullptr));
    std::wstring directory(name);
    std::wstring nested = directory + L"\\nested";
    assert(CreateDirectoryW(nested.c_str(), nullptr));
    std::wstring first = directory + L"\\first.lnk", second = directory + L"\\second.lnk";
    std::wstring other = nested + L"\\other.lnk";
    createLink(first); createLink(second); createLink(other);
    for (const auto& selection : {payload(first), payload(first, second)}) {
        assert(ShowShellContextMenu(nullptr, selection.c_str(), static_cast<UINT>(selection.size()), 20, 20) == S_FALSE);
    }
    assert(menus == 2);
    auto cross = payload(first, other);
    assert(ShowShellContextMenu(nullptr, cross.c_str(), static_cast<UINT>(cross.size()), 20, 20) == E_INVALIDARG);
    assert(menus == 2);
    RecordingContext context;
    assert(InvokeSelected(&context, nullptr, 0, {10, 20}) == S_FALSE);
    assert(context.invocations == 0);
    assert(SUCCEEDED(InvokeSelected(&context, nullptr, 1, {10, 20})));
    assert(context.invocations == 1);
    assert(reinterpret_cast<UINT_PTR>(context.received.lpVerbW) == 0);
    assert(context.received.fMask & CMIC_MASK_UNICODE);
    assert(context.received.ptInvoke.x == 10 && context.received.ptInvoke.y == 20);
    assert(SUCCEEDED(InvokeSelected(&context, nullptr, 37, {10, 20})));
    assert(reinterpret_cast<UINT_PTR>(context.received.lpVerbW) == 36);
    MenuHost host;
    host.second = &context;
    host.third = &context;
    WNDCLASSW cls{};
    cls.hInstance = GetModuleHandleW(nullptr);
    cls.lpfnWndProc = MenuHost::Procedure;
    cls.lpszClassName = L"Shortcut.TestContextForwarding";
    assert(RegisterClassW(&cls));
    HWND window = CreateWindowExW(0, cls.lpszClassName, L"", WS_POPUP, 0, 0, 0, 0,
                                  nullptr, nullptr, cls.hInstance, &host);
    assert(window);
    assert(SendMessageW(window, WM_MENUCHAR, 0, 0) == 777);
    assert(context.messages > 0);
    DestroyWindow(window);
    UnregisterClassW(cls.lpszClassName, cls.hInstance);
    assert(DeleteFileW(first.c_str())); assert(DeleteFileW(second.c_str())); assert(DeleteFileW(other.c_str()));
    assert(RemoveDirectoryW(nested.c_str())); assert(RemoveDirectoryW(directory.c_str()));
    // Release borrowed interfaces before leaving the COM apartment.
    host.third.Reset(); host.second.Reset();
    CoUninitialize();
    std::cout << "Native Shell menus: real single/multi selection, cancellation, validation and forwarding passed\n";
}
