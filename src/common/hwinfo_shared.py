"""Minimal HWiNFO64 Shared Memory v2 reader (Windows, stdlib only)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time


SM_NAME = "Global\\HWiNFO_SENS_SM2"
MUTEX_NAME = "Global\\HWiNFO_SM2_MUTEX"
FILE_MAP_READ = 0x0004
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
SIGNATURE_ACTIVE = 0x53695748  # HWiS
SIGNATURE_DEAD = 0x44414544  # DEAD
STRING_LEN = 128
UNIT_LEN = 16


class HWiNFOHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("signature", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("revision", ctypes.c_uint32),
        ("poll_time", ctypes.c_int64),
        ("sensor_offset", ctypes.c_uint32),
        ("sensor_size", ctypes.c_uint32),
        ("sensor_count", ctypes.c_uint32),
        ("reading_offset", ctypes.c_uint32),
        ("reading_size", ctypes.c_uint32),
        ("reading_count", ctypes.c_uint32),
        ("polling_period", ctypes.c_uint32),
    ]


class HWiNFOSensor(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("sensor_id", ctypes.c_uint32),
        ("sensor_inst", ctypes.c_uint32),
        ("name_orig", ctypes.c_char * STRING_LEN),
        ("name_user", ctypes.c_char * STRING_LEN),
    ]


class HWiNFOReading(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("reading_type", ctypes.c_uint32),
        ("sensor_index", ctypes.c_uint32),
        ("reading_id", ctypes.c_uint32),
        ("label_orig", ctypes.c_char * STRING_LEN),
        ("label_user", ctypes.c_char * STRING_LEN),
        ("unit", ctypes.c_char * UNIT_LEN),
        ("value", ctypes.c_double),
        ("value_min", ctypes.c_double),
        ("value_max", ctypes.c_double),
        ("value_avg", ctypes.c_double),
    ]


READING_TYPES = {
    1: "temp",
    2: "voltage",
    3: "fan",
    4: "current",
    5: "power",
    6: "clock",
    7: "usage",
    8: "other",
}


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.UnmapViewOfFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL


def _decode(buf: bytes) -> str:
    raw = bytes(buf).split(b"\0", 1)[0]
    if not raw:
        return ""
    if all(byte < 128 for byte in raw):
        return raw.decode("ascii", "replace").strip()
    candidates: list[str] = []
    for encoding in ("utf-8", "mbcs", "gbk"):
        try:
            candidates.append(raw.decode(encoding, "replace").strip())
        except (LookupError, UnicodeError):
            pass
    if not candidates:
        return raw.decode("utf-8", "ignore").strip()
    # HWiNFO user labels on this machine are ANSI/GBK while original labels
    # are ASCII. Prefer the candidate retaining the most CJK characters.
    def score(text: str) -> tuple[int, int]:
        cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
        replacement = text.count("�")
        return cjk * 10 - replacement, -len(text)

    return max(candidates, key=score)


def _open_mapping() -> tuple[int, int]:
    mapping = kernel32.OpenFileMappingW(FILE_MAP_READ, False, SM_NAME)
    if not mapping:
        error = ctypes.get_last_error()
        raise RuntimeError(f"HWiNFO shared memory unavailable (Win32 error {error})")
    pointer = kernel32.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0)
    if not pointer:
        error = ctypes.get_last_error()
        kernel32.CloseHandle(mapping)
        raise RuntimeError(f"HWiNFO shared memory map failed (Win32 error {error})")
    return int(mapping), int(pointer)


def read_snapshot() -> dict:
    mapping, pointer = _open_mapping()
    mutex = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
    locked = bool(mutex and kernel32.WaitForSingleObject(mutex, 100) == WAIT_OBJECT_0)
    try:
        header = HWiNFOHeader.from_buffer_copy(ctypes.string_at(pointer, ctypes.sizeof(HWiNFOHeader)))
        if header.signature == SIGNATURE_DEAD:
            raise RuntimeError("HWiNFO shared memory is marked DEAD")
        if header.signature != SIGNATURE_ACTIVE:
            raise RuntimeError(f"bad HWiNFO signature 0x{header.signature:08X}")
        sensors: list[str] = []
        for index in range(header.sensor_count):
            offset = header.sensor_offset + index * header.sensor_size
            sensor = HWiNFOSensor.from_buffer_copy(ctypes.string_at(pointer + offset, ctypes.sizeof(HWiNFOSensor)))
            sensors.append(_decode(sensor.name_user) or _decode(sensor.name_orig))
        readings: list[dict] = []
        for index in range(header.reading_count):
            offset = header.reading_offset + index * header.reading_size
            reading = HWiNFOReading.from_buffer_copy(ctypes.string_at(pointer + offset, ctypes.sizeof(HWiNFOReading)))
            readings.append(
                {
                    "type": READING_TYPES.get(reading.reading_type, "other"),
                    "sensor": sensors[reading.sensor_index] if reading.sensor_index < len(sensors) else "?",
                    "label": _decode(reading.label_user) or _decode(reading.label_orig),
                    "unit": _decode(reading.unit),
                    "value": float(reading.value),
                    "min": float(reading.value_min),
                    "max": float(reading.value_max),
                    "avg": float(reading.value_avg),
                }
            )
        return {
            "poll_time": int(header.poll_time),
            "polling_period": int(header.polling_period),
            "signature": int(header.signature),
            "sensors": sensors,
            "readings": readings,
            "read_at": time.time(),
        }
    finally:
        if locked:
            kernel32.ReleaseMutex(mutex)
        if mutex:
            kernel32.CloseHandle(mutex)
        kernel32.UnmapViewOfFile(pointer)
        kernel32.CloseHandle(mapping)


if __name__ == "__main__":
    import json

    snapshot = read_snapshot()
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
