"""Identificação do host com recursos nativos e fallback da biblioteca padrão."""

import os
import platform
import subprocess
from pathlib import Path


def processor_name() -> str | None:
    system = platform.system()
    fallback = platform.processor() or None
    try:
        if system == "Windows":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip() or fallback
        if system == "Linux":
            info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
            return next((line.partition(":")[2].strip() for line in info.splitlines()
                         if line.startswith("model name")), fallback)
    except OSError:
        pass
    return fallback


def physical_memory() -> int | None:
    """Retorna a memória física em bytes, quando o sistema a informa."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            kib = ctypes.c_ulonglong()
            if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kib)):
                return kib.value * 1024
        elif system == "Darwin":
            return int(subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"], encoding="utf-8", timeout=2,
                stderr=subprocess.DEVNULL,
            ))
        elif system == "Linux":
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None
