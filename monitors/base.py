"""
Base monitor interface for homelab monitoring system.
"""

import socket
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any, Dict


class BaseMetrics(ABC):
    """Base class for all metric data with serialization contract."""

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize metrics to dictionary format."""
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Get common metadata fields."""
        return {
            "metric_type": self.__class__.__name__,
            "timestamp": getattr(self, "timestamp", None),
            "hostname": getattr(self, "hostname", None),
            "enabled": getattr(self, "enabled", True),
        }


class BaseMonitor(ABC):
    """Base class for all monitoring implementations."""

    def __init__(self, name: str):
        self.name = name
        self.hostname = socket.gethostname()

    @abstractmethod
    def collect_metrics(self) -> BaseMetrics:
        """Collect metrics and return BaseMetrics instance."""
        pass

    def add_metadata(self, metrics: BaseMetrics) -> Dict[str, Any]:
        """Add common metadata to metrics."""
        return {
            "timestamp": time.time(),
            "hostname": self.hostname,
            "monitor_name": self.name,
            "metrics": metrics.to_dict(),
        }
