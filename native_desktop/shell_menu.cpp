// Standard IContextMenu integration; executes only the command the user selects.
#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <wrl/client.h>
#include <memory>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace {
struct PidlFree {
    using pointer = PIDLIST_RELATIVE;
    void operator()(pointer item) const { CoTaskMemFree(item); }
};
using Pidl = std::unique_ptr<ITEMIDLIST, PidlFree>;
struct MenuFree { void operator()(HMENU__* menu) const { DestroyMenu(menu); } };
using Menu = std::unique_ptr<HMENU__, MenuFree>;

struct MenuHost {
    ComPtr<IContextMenu2> second;
    ComPtr<IContextMenu3> third;
    static LRESULT CALLBACK Procedure(HWND window, UINT message, WPARAM wp, LPARAM lp) {
        auto self = reinterpret_cast<MenuHost*>(GetWindowLongPtrW(window, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<MenuHost*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);
            SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (self && (message == WM_INITMENUPOPUP || message == WM_DRAWITEM ||
                     message == WM_MEASUREITEM || message == WM_MENUCHAR)) {
            LRESULT result = 0;
            if (self->third && SUCCEEDED(self->third->HandleMenuMsg2(message, wp, lp, &result))) return result;
            if (message != WM_MENUCHAR && self->second &&
                SUCCEEDED(self->second->HandleMenuMsg(message, wp, lp))) return 0;
        }
        return DefWindowProcW(window, message, wp, lp);
    }
};
struct WindowFree { void operator()(HWND__* window) const { DestroyWindow(window); } };
using Window = std::unique_ptr<HWND__, WindowFree>;

HRESULT InvokeSelected(IContextMenu* context, HWND owner, UINT selected, POINT point) {
    if (!selected) return S_FALSE;
    CMINVOKECOMMANDINFOEX invoke{};
    invoke.cbSize = sizeof(invoke);
    invoke.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE;
    if (GetKeyState(VK_CONTROL) < 0) invoke.fMask |= CMIC_MASK_CONTROL_DOWN;
    if (GetKeyState(VK_SHIFT) < 0) invoke.fMask |= CMIC_MASK_SHIFT_DOWN;
    invoke.hwnd = owner;
    invoke.lpVerb = MAKEINTRESOURCEA(selected - 1);
    invoke.lpVerbW = MAKEINTRESOURCEW(selected - 1);
    invoke.nShow = SW_SHOWNORMAL;
    invoke.ptInvoke = point;
    return context->InvokeCommand(reinterpret_cast<CMINVOKECOMMANDINFO*>(&invoke));
}
}

extern "C" __declspec(dllexport) HRESULT WINAPI ShowShellContextMenu(
    HWND owner, const wchar_t* payload, UINT characters, int x, int y) {
    if (!payload || characters < 2 || characters > 4 * 1024 * 1024 ||
        payload[characters - 1] || payload[characters - 2]) return E_INVALIDARG;
    HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(initialized)) return initialized;
    struct Apartment { ~Apartment() { CoUninitialize(); } } apartment;
    try {
        std::vector<Pidl> items;
        std::vector<PCUITEMID_CHILD> children;
        ComPtr<IShellFolder> folder;
        Pidl parent;
        for (size_t offset = 0; offset < characters && payload[offset];) {
            size_t length = wcsnlen_s(payload + offset, characters - offset);
            if (offset + length >= characters || items.size() >= 10000) return E_INVALIDARG;
            PIDLIST_ABSOLUTE raw = nullptr;
            HRESULT hr = SHParseDisplayName(payload + offset, nullptr, &raw, 0, nullptr);
            if (FAILED(hr)) return hr;
            Pidl item(raw), currentParent(ILCloneFull(raw));
            if (!currentParent) return E_OUTOFMEMORY;
            ILRemoveLastID(currentParent.get());
            PCUITEMID_CHILD child = nullptr;
            ComPtr<IShellFolder> currentFolder;
            hr = SHBindToParent(item.get(), IID_PPV_ARGS(&currentFolder), &child);
            if (FAILED(hr)) return hr;
            if (!parent) { parent = std::move(currentParent); folder = currentFolder; }
            else if (!ILIsEqual(parent.get(), currentParent.get())) return E_INVALIDARG;
            children.push_back(child);
            items.push_back(std::move(item));
            offset += length + 1;
        }
        if (items.empty()) return E_INVALIDARG;
        ComPtr<IContextMenu> context;
        HRESULT hr = folder->GetUIObjectOf(owner, static_cast<UINT>(children.size()), children.data(),
                                           IID_IContextMenu, nullptr, &context);
        if (FAILED(hr)) return hr;
        MenuHost host;
        Window window;
        Menu menu(CreatePopupMenu());
        if (!menu) return E_OUTOFMEMORY;
        UINT flags = CMF_NORMAL;
        if (GetKeyState(VK_SHIFT) < 0) flags |= CMF_EXTENDEDVERBS;
        hr = context->QueryContextMenu(menu.get(), 0, 1, 0x7fff, flags);
        if (FAILED(hr)) return hr;
        context.As(&host.second);
        context.As(&host.third);
        HMODULE module = nullptr;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&ShowShellContextMenu), &module)) return HRESULT_FROM_WIN32(GetLastError());
        WNDCLASSW cls{};
        cls.hInstance = module;
        cls.lpfnWndProc = MenuHost::Procedure;
        cls.lpszClassName = L"Shortcut.NativeShellMenu";
        if (!RegisterClassW(&cls) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
            return HRESULT_FROM_WIN32(GetLastError());
        window.reset(CreateWindowExW(WS_EX_TOOLWINDOW, cls.lpszClassName, L"", WS_POPUP,
                                     x, y, 0, 0, owner, nullptr, module, &host));
        if (!window) return HRESULT_FROM_WIN32(GetLastError());
        ShowWindow(window.get(), SW_SHOWNOACTIVATE);
        SetForegroundWindow(window.get());
        UINT selected = static_cast<UINT>(TrackPopupMenuEx(menu.get(), TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                                          x, y, window.get(), nullptr));
        PostMessageW(window.get(), WM_NULL, 0, 0);
        return InvokeSelected(context.Get(), owner, selected, {x, y});
    } catch (...) { return E_FAIL; }
}
