#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <exdisp.h>
#include <shlguid.h>
#include <wrl/client.h>
#include <memory>
#include <vector>
#include <string>
#include <cstdint>
#include <atomic>

using Microsoft::WRL::ComPtr;
extern "C" HRESULT WINAPI Attach(IShellView*, PCIDLIST_ABSOLUTE, void**);
extern "C" HRESULT WINAPI SetPaths(void*, const wchar_t* const*, UINT);
extern "C" HRESULT WINAPI GetStats(void*, uint64_t*);
extern "C" HRESULT WINAPI Detach(void*);
extern "C" HRESULT WINAPI ObserveFailure(void*, HWND, UINT);

constexpr UINT READY = WM_APP + 0x351;
constexpr UINT CLOSED = WM_APP + 0x352;
constexpr UINT FILTER_ERROR = WM_APP + 0x353;
constexpr UINT REQUEST_STOP = WM_APP + 0x354;
constexpr wchar_t INIT[] = L"Shortcut.NativeDesktop.Connect.v1";

HRESULT DesktopView(IShellView** result) {
    ComPtr<IShellWindows> windows;
    HRESULT hr = CoCreateInstance(CLSID_ShellWindows, nullptr, CLSCTX_ALL, IID_PPV_ARGS(&windows));
    if (FAILED(hr)) return hr;
    VARIANT location{}, empty{};
    location.vt = VT_I4;
    location.lVal = CSIDL_DESKTOP;
    long handle = 0;
    ComPtr<IDispatch> dispatch;
    hr = windows->FindWindowSW(&location, &empty, SWC_DESKTOP, &handle, SWFO_NEEDDISPATCH, &dispatch);
    if (FAILED(hr)) return hr;
    if (!dispatch) return E_NOINTERFACE;
    ComPtr<IServiceProvider> service;
    hr = dispatch.As(&service);
    if (FAILED(hr)) return hr;
    ComPtr<IShellBrowser> browser;
    hr = service->QueryService(SID_STopLevelBrowser, IID_PPV_ARGS(&browser));
    return FAILED(hr) ? hr : browser->QueryActiveShellView(result);
}

struct Bridge {
    HWND window = nullptr, controller = nullptr, desktop = nullptr;
    HMODULE module = nullptr;
    HANDLE process = nullptr, ownerProcess = nullptr, closed = nullptr, requested = nullptr;
    void* filter = nullptr;
    ComPtr<IShellView> view;
    std::wstring className;
    HRESULT finalResult = S_OK;
    std::atomic<bool> closing{false};

    HRESULT Stop() {
        HRESULT hr = filter ? Detach(filter) : S_OK;
        if (FAILED(hr) && hr != E_PENDING) {
            // 恢复遇到 Shell 错误时让原视图重新枚举，文件本身始终未改动。
            view->Refresh();
            hr = Detach(filter);
        }
        if (SUCCEEDED(hr)) filter = nullptr;
        return hr;
    }

    static LRESULT CALLBACK Procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp) {
        auto self = reinterpret_cast<Bridge*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<Bridge*>(reinterpret_cast<CREATESTRUCTW*>(lp)->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (!self) return DefWindowProcW(hwnd, message, wp, lp);
        if (message == WM_COPYDATA && reinterpret_cast<HWND>(wp) == self->controller) {
            auto data = reinterpret_cast<COPYDATASTRUCT*>(lp);
            try {
                if (data->dwData == 1) {
                    // WM_COPYDATA 由 Windows 复制；长度检查只保护协议边界。
                    if (data->cbData < 2 || data->cbData % 2 || data->cbData > 8 * 1024 * 1024)
                        return E_INVALIDARG;
                    auto begin = static_cast<const wchar_t*>(data->lpData);
                    size_t length = data->cbData / sizeof(wchar_t);
                    if (begin[length - 1]) return E_INVALIDARG;
                    std::vector<const wchar_t*> paths;
                    for (size_t index = 0; index < length && begin[index];) {
                        paths.push_back(begin + index);
                        index += wcsnlen_s(begin + index, length - index) + 1;
                    }
                    return SetPaths(self->filter, paths.data(), static_cast<UINT>(paths.size()));
                }
                if (data->dwData == 2) {
                    uint64_t stats[6]{};
                    HRESULT hr = GetStats(self->filter, stats);
                    COPYDATASTRUCT reply{2, sizeof(stats), stats};
                    DWORD_PTR ignored = 0;
                    SendMessageTimeoutW(self->controller, WM_COPYDATA, reinterpret_cast<WPARAM>(hwnd),
                        reinterpret_cast<LPARAM>(&reply), SMTO_ABORTIFHUNG, 1000, &ignored);
                    return hr;
                }
            } catch (...) { return E_FAIL; }
        }
        if (message == FILTER_ERROR) {
            self->finalResult = static_cast<HRESULT>(lp);
            SetEvent(self->requested);
            return 0;
        }
        if (message == REQUEST_STOP) {
            SetEvent(self->requested);
            return 0;
        }
        if (message == WM_CLOSE) {
            // COM Refresh/Release 可能泵送另一个关闭消息，不能让内层先销毁上下文。
            if (self->closing.exchange(true)) return E_PENDING;
            struct LeaveClose {
                std::atomic<bool>& flag;
                ~LeaveClose() { flag.store(false); }
            } leave{self->closing};
            HRESULT hr = self->Stop();
            if (FAILED(hr)) {
                return hr; // 保留上下文，Shell 回调退出后可由工作线程重试。
            }
            self->view.Reset();
            DestroyWindow(hwnd);
            return 0;
        }
        if (message == WM_NCDESTROY) {
            SetEvent(self->closed);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        }
        return DefWindowProcW(hwnd, message, wp, lp);
    }

    static DWORD WINAPI WatchController(void* parameter) {
        auto self = static_cast<Bridge*>(parameter);
        std::vector<HANDLE> events{self->requested, self->process, self->closed};
        if (self->ownerProcess) events.push_back(self->ownerProcess);
        WaitForMultipleObjects(static_cast<DWORD>(events.size()), events.data(), FALSE, INFINITE);
        // 恢复由本线程同步请求；返回时桌面线程已经离开整个窗口回调，才可卸载 DLL。
        // 空闲等待内核事件；只有退出恢复受阻时重试，Explorer 恢复响应后继续完成清理。
        HRESULT hr = E_FAIL;
        for (;;) {
            DWORD_PTR result = 0;
            if (WaitForSingleObject(self->closed, 0) == WAIT_OBJECT_0) {
                // WM_NCDESTROY 可在超时的 WM_CLOSE 中稍后完成；同步屏障保证回调已经退栈。
                if (self->closing.load()) {
                    hr = E_PENDING;
                } else if (SendMessageTimeoutW(self->desktop, WM_NULL, 0, 0,
                    SMTO_ABORTIFHUNG, 5000, &result)) { hr = S_OK; break; }
            } else if (SendMessageTimeoutW(self->window, WM_CLOSE, 0, 0,
                SMTO_ABORTIFHUNG, 5000, &result)) {
                hr = static_cast<HRESULT>(result);
                if (SUCCEEDED(hr)) break;
            } else {
                hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT);
            }
            Sleep(hr == E_PENDING ? 60 : 1000);
        }
        PostMessageW(self->controller, CLOSED, 0, FAILED(hr) ? hr : self->finalResult);
        HMODULE module = self->module;
        bool unregistered = UnregisterClassW(self->className.c_str(), module) != FALSE;
        CloseHandle(self->process);
        if (self->ownerProcess) CloseHandle(self->ownerProcess);
        CloseHandle(self->closed);
        CloseHandle(self->requested);
        delete self;
        if (unregistered) FreeLibraryAndExitThread(module, 0);
        // Explorer 无响应时宁可保留一个模块引用，也不卸载仍在执行的代码。
        return 0;
    }
};

HRESULT Connect(HWND controller, DWORD ownerPid, HWND* result) {
    *result = nullptr;
    auto self = std::make_unique<Bridge>();
    self->controller = controller;
    HRESULT hr = DesktopView(&self->view);
    if (FAILED(hr)) return hr;
    hr = self->view->GetWindow(&self->desktop);
    if (FAILED(hr)) return hr;
    DWORD pid = 0;
    GetWindowThreadProcessId(controller, &pid);
    self->process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (ownerPid && ownerPid != pid)
        self->ownerProcess = OpenProcess(SYNCHRONIZE, FALSE, ownerPid);
    self->closed = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    self->requested = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!self->process || !self->closed || !self->requested ||
        (ownerPid && ownerPid != pid && !self->ownerProcess)) hr = E_FAIL;
    if (SUCCEEDED(hr) && !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
        reinterpret_cast<LPCWSTR>(&Connect), &self->module)) hr = E_FAIL;
    self->className = L"Shortcut.NativeDesktop." + std::to_wstring(reinterpret_cast<UINT_PTR>(controller));
    WNDCLASSW wc{};
    wc.lpfnWndProc = Bridge::Procedure;
    wc.hInstance = self->module;
    wc.lpszClassName = self->className.c_str();
    if (SUCCEEDED(hr) && !RegisterClassW(&wc)) hr = E_FAIL;
    if (SUCCEEDED(hr)) {
        self->window = CreateWindowExW(0, wc.lpszClassName, L"", 0, 0, 0, 0, 0,
            HWND_MESSAGE, nullptr, self->module, self.get());
        if (!self->window) hr = E_FAIL;
    }
    if (SUCCEEDED(hr)) {
        // 先准备完句柄、窗口和模块引用，再安装 Shell 回调，缩小撤销失败的范围。
        ITEMIDLIST root{};
        hr = Attach(self->view.Get(), &root, &self->filter);
    }
    if (SUCCEEDED(hr)) {
        ObserveFailure(self->filter, self->window, FILTER_ERROR);
        HANDLE worker = CreateThread(nullptr, 0, Bridge::WatchController, self.get(), 0, nullptr);
        if (worker) {
            CloseHandle(worker);
            *result = self->window;
            self.release();
            return S_OK;
        }
        hr = E_FAIL;
    }
    if (FAILED(self->Stop())) {
        // 无法撤销回调时必须保留其代码和上下文；尚未投递 paths，不会收起任何项目。
        // 延迟关闭以及下一次连接的遗留窗口清理可再次尝试恢复。
        if (self->window) PostMessageW(self->window, WM_CLOSE, 0, 0);
        self.release();
        return hr;
    }
    if (self->window) DestroyWindow(self->window);
    if (self->module) {
        UnregisterClassW(wc.lpszClassName, self->module);
        FreeLibrary(self->module); // 启动钩子仍持有系统引用，此处不会卸载正在执行的回调。
    }
    if (self->closed) CloseHandle(self->closed);
    if (self->requested) CloseHandle(self->requested);
    if (self->process) CloseHandle(self->process);
    if (self->ownerProcess) CloseHandle(self->ownerProcess);
    return hr;
}

extern "C" __declspec(dllexport) LRESULT CALLBACK DesktopConnect(int code, WPARAM wp, LPARAM lp) {
    if (code >= 0 && wp == PM_REMOVE) {
        auto msg = reinterpret_cast<MSG*>(lp);
        if (msg->message == RegisterWindowMessageW(INIT)) {
            HWND result = nullptr;
            HRESULT hr = E_FAIL;
            try { hr = Connect(reinterpret_cast<HWND>(msg->wParam), static_cast<DWORD>(msg->lParam), &result); }
            catch (...) { hr = E_FAIL; }
            PostMessageW(reinterpret_cast<HWND>(msg->wParam), READY, reinterpret_cast<WPARAM>(result), hr);
            msg->message = WM_NULL;
        }
    }
    return CallNextHookEx(nullptr, code, wp, lp);
}
