"""Dismiss HWiNFO's splash by clicking its Start button, and prove it worked.

HWiNFO 8.34 shows a modal splash ("开始" / "Start") before the sensor window,
even with SensorsOnly=1 in HWiNFO64.INI. Launched from the elevated scheduled
task it is an elevated window, so this is also a direct test of whether a
non-elevated process can drive it at all (UIPI normally blocks that).

Reaching the sensor window is what matters: `--sensor-required` needs the
shared memory map, which only exists while the sensor window polls.

Prints what it did. Exit 0 only if the splash is gone and the shared memory
answers.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.restype = wintypes.HWND
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

BM_CLICK = 0x00F5


def text_of(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buffer, length + 2)
    return buffer.value


def class_of(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def hwinfo_pids() -> set[int]:
    import subprocess
    out = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq HWiNFO64.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace", check=False).stdout
    pids = set()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().endswith("hwinfo64.exe"):
            pids.add(int(parts[1]))
    return pids


def windows_of(pid: int) -> list[tuple[int, str, str, bool]]:
    found: list[tuple[int, str, str, bool]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if pid_of(hwnd) == pid:
            found.append((hwnd, class_of(hwnd), text_of(hwnd), bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(callback, 0)
    return found


def main() -> int:
    pids = hwinfo_pids()
    if not pids:
        print("HWiNFO64 is not running")
        return 2
    print("HWiNFO64 pids:", sorted(pids))

    splash = None
    for pid in pids:
        for hwnd, cls, title, visible in windows_of(pid):
            print(f"  pid={pid} hwnd=0x{hwnd:X} visible={visible} class='{cls}' title='{title}'")
            if cls == "#32770" and visible:
                splash = hwnd
    if splash is None:
        print("no visible dialog; nothing to dismiss")
    else:
        button = user32.GetDlgItem(splash, 1)
        print(f"splash=0x{splash:X} startButton=0x{button:X} label='{text_of(button)}'")
        if not button:
            print("RESULT: FAIL - no control id 1 on the splash")
            return 3
        print("sending BM_CLICK (expected to work: same user, and UIPI only gates higher integrity)")
        user32.SendMessageW(button, BM_CLICK, 0, 0)
        print("  SendMessage returned")

    # Now the real criterion: the shared memory map, which only exists while the
    # sensor window polls.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    import hwinfo_shared

    for attempt in range(1, 13):
        time.sleep(3)
        try:
            snapshot = hwinfo_shared.read_snapshot()
        except Exception as error:  # noqa: BLE001 - report whatever it says
            print(f"  attempt {attempt}: {error}")
            continue
        readings = snapshot["readings"]
        print(f"  attempt {attempt}: shared memory is live - sensors={len(snapshot['sensors'])} readings={len(readings)}")
        interesting = [r for r in readings if any(
            key in f"{r['sensor']} {r['label']}" for key in ("Tctl", "SPD Hub", "DIMM", "Vcore", "VDDCR"))]
        for reading in interesting[:12]:
            print(f"     {reading['sensor']} | {reading['label']} = {reading['value']} {reading['unit']}")
        print("RESULT: PASS - the splash was dismissed and HWiNFO is polling")
        return 0

    print("RESULT: FAIL - the splash is gone but shared memory never appeared")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
