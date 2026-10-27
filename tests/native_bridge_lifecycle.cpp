// Execute the production watchdog with fake Win32 waits/messages. No Explorer access.
#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <shlobj.h>
#include <exdisp.h>
#include <shlguid.h>
#include <wrl/client.h>
#include <cassert>
#include <iostream>
#include <vector>

namespace {
    unsigned sends = 0, pauses = 0, barriers = 0, unloads = 0, notifications = 0;
    bool closed = false, delayedClose = false;
    DWORD signaled = 3, waitedCount = 0;
    std::vector<HANDLE> waited, released;
    void* currentBridge = nullptr;
    bool reenterDetach = false;
    unsigned detachCalls = 0;
    void (*pauseCallback)() = nullptr;

    LONG_PTR WINAPI FakeGetWindowLongPtrW(HWND, int) {
        return reinterpret_cast<LONG_PTR>(currentBridge);
    }

    DWORD WINAPI FakeWaitForMultipleObjects(DWORD count, const HANDLE* handles, BOOL, DWORD) {
        waitedCount = count;
        waited.assign(handles, handles + count);
        return WAIT_OBJECT_0 + signaled;
    }
    DWORD WINAPI FakeWaitForSingleObject(HANDLE, DWORD) {
        return closed ? WAIT_OBJECT_0 : WAIT_TIMEOUT;
    }
    LRESULT WINAPI FakeSendMessageTimeoutW(HWND, UINT message, WPARAM, LPARAM,
                                          UINT, UINT, PDWORD_PTR result) {
        if (message == WM_NULL) { ++barriers; *result = 0; return TRUE; }
        assert(message == WM_CLOSE);
        ++sends;
        if (sends == 1) {
            closed = delayedClose;
            return FALSE; // Explorer is temporarily unresponsive.
        }
        if (sends == 2) { *result = static_cast<DWORD_PTR>(E_PENDING); return TRUE; }
        // Recover after more than the old five-attempt budget.
        if (sends < 8) { *result = static_cast<DWORD_PTR>(E_FAIL); return TRUE; }
        closed = true;
        *result = S_OK;
        return TRUE;
    }
    void WINAPI FakeSleep(DWORD delay) {
        assert(delay == 60 || delay == 1000);
        ++pauses;
        if (pauseCallback) pauseCallback();
    }
    BOOL WINAPI FakePostMessageW(HWND, UINT, WPARAM, LPARAM) { ++notifications; return TRUE; }
    BOOL WINAPI FakeUnregisterClassW(LPCWSTR, HINSTANCE) { return TRUE; }
    BOOL WINAPI FakeCloseHandle(HANDLE handle) { released.push_back(handle); return TRUE; }
    void WINAPI FakeFreeLibraryAndExitThread(HMODULE, DWORD) { ++unloads; }
}

#define WaitForMultipleObjects FakeWaitForMultipleObjects
#define WaitForSingleObject FakeWaitForSingleObject
#define SendMessageTimeoutW FakeSendMessageTimeoutW
#define Sleep FakeSleep
#define PostMessageW FakePostMessageW
#define UnregisterClassW FakeUnregisterClassW
#define CloseHandle FakeCloseHandle
#define FreeLibraryAndExitThread FakeFreeLibraryAndExitThread
#define GetWindowLongPtrW FakeGetWindowLongPtrW
#include "../native_desktop/bridge.cpp"

// Link-only stubs: WatchController never invokes COM or the filter in this harness.
extern "C" HRESULT WINAPI Attach(IShellView*, PCIDLIST_ABSOLUTE, void**) { return E_NOTIMPL; }
extern "C" HRESULT WINAPI SetPaths(void*, const wchar_t* const*, UINT) { return E_NOTIMPL; }
extern "C" HRESULT WINAPI GetStats(void*, uint64_t*) { return E_NOTIMPL; }
extern "C" HRESULT WINAPI Detach(void*) {
    ++detachCalls;
    if (reenterDetach) {
        reenterDetach = false;
        auto bridge = static_cast<Bridge*>(currentBridge);
        assert(Bridge::Procedure(bridge->window, WM_CLOSE, 0, 0) == E_PENDING);
    }
    return E_PENDING;
}
extern "C" HRESULT WINAPI ObserveFailure(void*, HWND, UINT) { return E_NOTIMPL; }

static HANDLE handle(INT_PTR value) { return reinterpret_cast<HANDLE>(value); }

static void run(bool delayed, bool alreadyClosed, bool hasOwner, bool unwinding = false) {
    sends = pauses = barriers = unloads = notifications = 0;
    closed = alreadyClosed;
    delayedClose = delayed;
    signaled = alreadyClosed ? 2 : hasOwner ? 3 : 1;
    released.clear();
    auto bridge = new Bridge();
    bridge->window = reinterpret_cast<HWND>(handle(1));
    bridge->desktop = reinterpret_cast<HWND>(handle(2));
    bridge->controller = reinterpret_cast<HWND>(handle(3));
    bridge->process = handle(4);
    bridge->closed = handle(5);
    bridge->requested = handle(6);
    bridge->module = reinterpret_cast<HMODULE>(handle(7));
    bridge->ownerProcess = hasOwner ? handle(8) : nullptr;
    bridge->closing.store(unwinding);
    currentBridge = bridge;
    pauseCallback = unwinding ? +[]() {
        if (pauses == 2) static_cast<Bridge*>(currentBridge)->closing.store(false);
    } : nullptr;
    Bridge::WatchController(bridge);
    currentBridge = nullptr;
    pauseCallback = nullptr;
    assert(waitedCount == (hasOwner ? 4u : 3u));
    assert(waited[1] == handle(4));
    if (hasOwner) assert(waited[3] == handle(8));
    assert(released.size() == (hasOwner ? 4u : 3u));
    assert(unloads == 1 && notifications == 1);
    if (unwinding) assert(sends == 0 && barriers == 1 && pauses == 2);
    else if (alreadyClosed) assert(sends == 0 && barriers == 1);
    else if (delayed) assert(sends == 1 && barriers == 1 && pauses == 1);
    else assert(sends == 8 && pauses == 7 && barriers == 0);
}

int main() {
    run(false, false, true);  // Main Shortcut exits while helper remains alive.
    run(false, false, false); // Legacy helper-only connection dies.
    run(true, false, true);   // A timed-out close completes asynchronously.
    run(false, true, true);   // An external close still needs a callback barrier.
    run(false, true, true, true); // Closed signal cannot unload an active close callback.
    Bridge bridge;
    bridge.filter = handle(10);
    currentBridge = &bridge;
    reenterDetach = true;
    assert(Bridge::Procedure(nullptr, WM_CLOSE, 0, 0) == E_PENDING);
    assert(detachCalls == 1 && !bridge.closing.load());
    currentBridge = nullptr;
    std::cout << "6 native watchdog lifecycle scenarios passed\n";
}
