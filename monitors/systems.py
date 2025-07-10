"""
System metrics collection using psutil.

Uses dataclasses to hold actual metric values with clear field names.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psutil

from monitors.base import BaseMonitor


@dataclass
class BaseMetrics:
    """Base metrics class with common metadata."""

    enabled: bool = True
    timestamp: Optional[float] = None
    hostname: Optional[str] = None


@dataclass
class CPUMetrics(BaseMetrics):
    """CPU metrics data."""

    percent: float = 0.0
    per_core: List[float] = None
    cores: int = 0
    cores_logical: int = 0
    user_time: float = 0.0
    system_time: float = 0.0
    idle_time: float = 0.0
    iowait_time: float = 0.0


@dataclass
class MemoryMetrics(BaseMetrics):
    """Memory metrics data."""

    total: int = 0
    available: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0
    buffers: int = 0
    cached: int = 0
    # Swap
    swap_total: int = 0
    swap_used: int = 0
    swap_free: int = 0
    swap_percent: float = 0.0


@dataclass
class DiskMetrics(BaseMetrics):
    """Disk metrics data."""

    # Usage by mount point (stored as dict)
    usage: Dict[str, Dict[str, Any]] = None
    # I/O totals
    read_count: int = 0
    write_count: int = 0
    read_bytes: int = 0
    write_bytes: int = 0
    read_time: int = 0
    write_time: int = 0


@dataclass
class NetworkMetrics(BaseMetrics):
    """Network metrics data."""

    # Per interface (stored as dict)
    interfaces: Dict[str, Dict[str, int]] = None
    # Totals
    total_bytes_sent: int = 0
    total_bytes_recv: int = 0
    total_packets_sent: int = 0
    total_packets_recv: int = 0


@dataclass
class LoadMetrics(BaseMetrics):
    """System load metrics data."""

    load_1min: float = 0.0
    load_5min: float = 0.0
    load_15min: float = 0.0


@dataclass
class SystemMetrics(BaseMetrics):
    """Complete system metrics collection."""

    cpu: CPUMetrics = None
    memory: MemoryMetrics = None
    disk: DiskMetrics = None
    network: NetworkMetrics = None
    load: LoadMetrics = None


class SystemMonitor(BaseMonitor):
    """Monitor for local system metrics using psutil."""

    def __init__(self, name: str):
        super().__init__(name)

    def collect_metrics(self) -> SystemMetrics:
        """Collect all system metrics into structured dataclasses."""
        import time

        # Create main metrics container
        metrics = SystemMetrics(timestamp=time.time(), hostname=self.hostname)

        # Collect each metric type
        metrics.cpu = self.collect_cpu_metrics()
        metrics.memory = self.collect_memory_metrics()
        metrics.disk = self.collect_disk_metrics()
        metrics.network = self.collect_network_metrics()
        metrics.load = self.collect_load_metrics()

        return metrics

    def collect_cpu_metrics(self) -> CPUMetrics:
        """Collect CPU metrics."""
        # Get CPU percentage with 1 second interval
        cpu_percent = psutil.cpu_percent(interval=1)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        cpu_times = psutil.cpu_times()

        return CPUMetrics(
            percent=cpu_percent,
            per_core=per_core,
            cores=psutil.cpu_count(),
            cores_logical=psutil.cpu_count(logical=True),
            user_time=cpu_times.user,
            system_time=cpu_times.system,
            idle_time=cpu_times.idle,
            iowait_time=getattr(cpu_times, "iowait", 0.0),
        )

    def collect_memory_metrics(self) -> MemoryMetrics:
        """Collect memory metrics."""
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return MemoryMetrics(
            total=memory.total,
            available=memory.available,
            used=memory.used,
            free=memory.free,
            percent=memory.percent,
            buffers=getattr(memory, "buffers", 0),
            cached=getattr(memory, "cached", 0),
            swap_total=swap.total,
            swap_used=swap.used,
            swap_free=swap.free,
            swap_percent=swap.percent,
        )

    def collect_disk_metrics(self) -> DiskMetrics:
        """Collect disk metrics."""
        # Collect disk usage
        partitions = psutil.disk_partitions()
        usage_data = {}

        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                usage_data[partition.mountpoint] = {
                    "device": partition.device,
                    "fstype": partition.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": (usage.used / usage.total) * 100
                    if usage.total > 0
                    else 0,
                }
            except (PermissionError, OSError):
                continue

        # Collect disk I/O
        disk_io = psutil.disk_io_counters()
        if disk_io:
            return DiskMetrics(
                usage=usage_data,
                read_count=disk_io.read_count,
                write_count=disk_io.write_count,
                read_bytes=disk_io.read_bytes,
                write_bytes=disk_io.write_bytes,
                read_time=disk_io.read_time,
                write_time=disk_io.write_time,
            )
        else:
            return DiskMetrics(usage=usage_data)

    def collect_network_metrics(self) -> NetworkMetrics:
        """Collect network metrics."""
        net_io = psutil.net_io_counters(pernic=True)
        interfaces_data = {}

        total_sent = 0
        total_recv = 0
        total_packets_sent = 0
        total_packets_recv = 0

        for interface, stats in net_io.items():
            # Skip loopback
            if interface.startswith("lo"):
                continue

            interfaces_data[interface] = {
                "bytes_sent": stats.bytes_sent,
                "bytes_recv": stats.bytes_recv,
                "packets_sent": stats.packets_sent,
                "packets_recv": stats.packets_recv,
                "errin": stats.errin,
                "errout": stats.errout,
                "dropin": stats.dropin,
                "dropout": stats.dropout,
            }

            # Add to totals
            total_sent += stats.bytes_sent
            total_recv += stats.bytes_recv
            total_packets_sent += stats.packets_sent
            total_packets_recv += stats.packets_recv

        return NetworkMetrics(
            interfaces=interfaces_data,
            total_bytes_sent=total_sent,
            total_bytes_recv=total_recv,
            total_packets_sent=total_packets_sent,
            total_packets_recv=total_packets_recv,
        )

    def collect_load_metrics(self) -> LoadMetrics:
        """Collect system load metrics."""
        try:
            load_avg = psutil.getloadavg()
            return LoadMetrics(
                load_1min=load_avg[0], load_5min=load_avg[1], load_15min=load_avg[2]
            )
        except AttributeError:
            # getloadavg not available on all platforms
            return LoadMetrics()
