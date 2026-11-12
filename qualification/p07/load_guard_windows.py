"""Mesures natives Windows et Job Object limité au processus d'essai créé par le parent."""

import ctypes as c
import os
import time
from pathlib import Path

from common import QualificationError

MIB = 1024**2


class Performance(c.Structure):
    _fields_ = [("cb", c.c_ulong)] + [(name, c.c_size_t) for name in (
        "commit", "limit", "peak", "physical", "available", "cache", "kernel",
        "kernel_paged", "kernel_nonpaged", "page_size",
    )] + [(name, c.c_ulong) for name in ("handles", "processes", "threads")]


class GpuMemory(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in ("total", "free", "used")]


class CounterValue(c.Structure):
    _fields_ = [("status", c.c_ulong), ("value", c.c_double)]


class Telemetry:
    """RAM physique/commit, NVML global et défauts de page avec lecture disque."""

    def __init__(self):
        system = Path(os.environ["SystemRoot"]) / "System32"
        self.psapi = c.WinDLL(str(system / "psapi.dll"), use_last_error=True)
        self.psapi.GetPerformanceInfo.argtypes = [c.POINTER(Performance), c.c_ulong]
        self.psapi.GetPerformanceInfo.restype = c.c_int
        self.nvml = c.WinDLL(str(system / "nvml.dll"))
        self.nvml.nvmlInit_v2.argtypes = []
        self.nvml.nvmlInit_v2.restype = c.c_int
        self.nvml.nvmlShutdown.argtypes = []
        self.nvml.nvmlShutdown.restype = c.c_int
        self.nvml.nvmlDeviceGetHandleByIndex_v2.argtypes = [c.c_uint, c.POINTER(c.c_void_p)]
        self.nvml.nvmlDeviceGetHandleByIndex_v2.restype = c.c_int
        self.nvml.nvmlDeviceGetMemoryInfo.argtypes = [c.c_void_p, c.POINTER(GpuMemory)]
        self.nvml.nvmlDeviceGetMemoryInfo.restype = c.c_int
        if self.nvml.nvmlInit_v2():
            raise QualificationError("NVML indisponible : chargement interdit.")
        self.device = c.c_void_p()
        if self.nvml.nvmlDeviceGetHandleByIndex_v2(0, c.byref(self.device)):
            raise QualificationError("GPU de qualification indisponible.")
        self.pdh = c.WinDLL(str(system / "pdh.dll"))
        self.pdh.PdhOpenQueryW.argtypes = [c.c_wchar_p, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhOpenQueryW.restype = c.c_ulong
        self.pdh.PdhAddEnglishCounterW.argtypes = [
            c.c_void_p, c.c_wchar_p, c.c_size_t, c.POINTER(c.c_void_p),
        ]
        self.pdh.PdhAddEnglishCounterW.restype = c.c_ulong
        self.pdh.PdhCollectQueryData.argtypes = [c.c_void_p]
        self.pdh.PdhCollectQueryData.restype = c.c_ulong
        self.pdh.PdhGetFormattedCounterValue.argtypes = [
            c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(CounterValue),
        ]
        self.pdh.PdhGetFormattedCounterValue.restype = c.c_ulong
        self.pdh.PdhCloseQuery.argtypes = [c.c_void_p]
        self.pdh.PdhCloseQuery.restype = c.c_ulong
        self.query = c.c_void_p()
        if self.pdh.PdhOpenQueryW(None, 0, c.byref(self.query)):
            raise QualificationError("Compteurs Windows indisponibles.")
        self.counters = {}
        for name, path in {"page_reads_per_s": r"\Memory\Page Reads/sec",
                           "pages_input_per_s": r"\Memory\Pages Input/sec"}.items():
            handle = c.c_void_p()
            if self.pdh.PdhAddEnglishCounterW(self.query, path, 0, c.byref(handle)):
                raise QualificationError("Compteur de pagination indisponible.")
            self.counters[name] = handle
        self.pdh.PdhCollectQueryData(self.query)

    def read(self):
        memory = Performance()
        memory.cb = c.sizeof(memory)
        if not self.psapi.GetPerformanceInfo(c.byref(memory), memory.cb):
            raise QualificationError("Mesure mémoire perdue : arrêt requis.")
        gpu = GpuMemory()
        if self.nvml.nvmlDeviceGetMemoryInfo(self.device, c.byref(gpu)):
            raise QualificationError("Mesure GPU perdue : arrêt requis.")
        if self.pdh.PdhCollectQueryData(self.query):
            raise QualificationError("Mesure pagination perdue : arrêt requis.")
        result = {
            "monotonic_s": time.monotonic(),
            "ram_available_mib": round(memory.available * memory.page_size / MIB, 2),
            "commit_headroom_mib": round(
                (memory.limit - memory.commit) * memory.page_size / MIB, 2,
            ),
            "commit_percent": round(100 * memory.commit / memory.limit, 2),
            "vram_free_mib": round(gpu.free / MIB, 2),
            "vram_used_mib": round(gpu.used / MIB, 2),
        }
        for name, handle in self.counters.items():
            value = CounterValue()
            status = self.pdh.PdhGetFormattedCounterValue(handle, 0x200, None, c.byref(value))
            if status or value.status not in (0, 1):
                raise QualificationError("Mesure pagination invalide : arrêt requis.")
            result[name] = round(max(0, value.value), 2)
        return result

    def close(self):
        self.pdh.PdhCloseQuery(self.query)
        self.nvml.nvmlShutdown()


class BasicLimits(c.Structure):
    _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong),
                ("flags", c.c_ulong), ("min_ws", c.c_size_t), ("max_ws", c.c_size_t),
                ("process_count", c.c_ulong), ("affinity", c.c_size_t),
                ("priority", c.c_ulong), ("scheduling", c.c_ulong)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in (
        "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes",
    )]


class ExtendedLimits(c.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process_memory", c.c_size_t), ("peak_job_memory", c.c_size_t)]


class ChildJob:
    """Kill-on-close + plafond de commit privé ; aucun PID utilisateur accepté en CLI."""

    def __init__(self, private_limit_mib):
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, c.c_wchar_p]
        self.kernel.CreateJobObjectW.restype = c.c_void_p
        self.kernel.SetInformationJobObject.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_ulong]
        self.kernel.SetInformationJobObject.restype = c.c_int
        self.kernel.QueryInformationJobObject.argtypes = [
            c.c_void_p, c.c_int, c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong),
        ]
        self.kernel.QueryInformationJobObject.restype = c.c_int
        self.kernel.OpenProcess.argtypes = [c.c_ulong, c.c_int, c.c_ulong]
        self.kernel.OpenProcess.restype = c.c_void_p
        self.kernel.AssignProcessToJobObject.argtypes = [c.c_void_p, c.c_void_p]
        self.kernel.AssignProcessToJobObject.restype = c.c_int
        self.kernel.TerminateJobObject.argtypes = [c.c_void_p, c.c_uint]
        self.kernel.TerminateJobObject.restype = c.c_int
        self.kernel.CloseHandle.argtypes = [c.c_void_p]
        self.kernel.CloseHandle.restype = c.c_int
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise QualificationError("Job Object indisponible : essai interdit.")
        limits = ExtendedLimits()
        # Windows venv lance un redirecteur puis le véritable Python : deux membres au maximum.
        limits.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8
        limits.basic.process_count = 2
        limits.process_memory = int(private_limit_mib * MIB)
        limits.job_memory = int((private_limit_mib + 64) * MIB)
        applied = self.kernel.SetInformationJobObject(
            self.handle, 9, c.byref(limits), c.sizeof(limits),
        )
        if not applied:
            self.close()
            raise QualificationError("Limites Windows non appliquées : essai interdit.")

    def attach(self, process):
        handle = self.kernel.OpenProcess(0x101, False, process.pid)
        if not handle:
            raise QualificationError("Processus d'essai inaccessible.")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                raise QualificationError("Protection du processus impossible : essai interdit.")
        finally:
            self.kernel.CloseHandle(handle)

    def stop(self):
        if not self.kernel.TerminateJobObject(self.handle, 125):
            raise QualificationError("Arrêt du Job Object impossible.")

    def resume(self, process):
        """Popen est créé suspendu : aucun descendant ne précède l'attachement au Job Object."""
        import psutil
        threads = psutil.Process(process.pid).threads()
        if len(threads) != 1:
            raise QualificationError("Thread initial inattendu : essai interdit.")
        self.kernel.OpenThread.argtypes = [c.c_ulong, c.c_int, c.c_ulong]
        self.kernel.OpenThread.restype = c.c_void_p
        self.kernel.ResumeThread.argtypes = [c.c_void_p]
        self.kernel.ResumeThread.restype = c.c_ulong
        handle = self.kernel.OpenThread(0x2, False, threads[0].id)
        if not handle:
            raise QualificationError("Thread du processus d'essai inaccessible.")
        try:
            if self.kernel.ResumeThread(handle) != 1:
                raise QualificationError("Reprise contrôlée du processus impossible.")
        finally:
            self.kernel.CloseHandle(handle)

    def member_pids(self):
        """Membres réellement attachés au job, sans inclure les rapporteurs WER externes."""
        class PidList(c.Structure):
            _fields_ = [("assigned", c.c_ulong), ("count", c.c_ulong),
                        ("pids", c.c_size_t * 16)]
        values = PidList()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 3, c.byref(values), c.sizeof(values), None,
        ) or values.count > 16:
            raise QualificationError("Lecture des membres du job impossible.")
        return list(values.pids[:values.count])

    def memory_peaks(self):
        """Pics de mémoire engagée suivis par Windows, indépendants de l'échantillonnage."""
        limits = ExtendedLimits()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 9, c.byref(limits), c.sizeof(limits), None,
        ):
            raise QualificationError("Lecture des pics du job impossible.")
        return {"peak_single_process_commit_mib": round(limits.peak_process_memory / MIB, 2),
                "peak_job_commit_mib": round(limits.peak_job_memory / MIB, 2)}

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
