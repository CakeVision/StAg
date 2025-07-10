"""
Base monitor interface for homelab monitoring system.

Defines the common interface that all monitors implement.
"""

import socket
import time
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseMonitor(ABC):
    """Base class for all monitoring implementations."""

    def __init__(self, name: str):
        self.name = name
        self.hostname = socket.gethostname()

    @abstractmethod
    def collect_metrics(self) -> Dict[str, Any]:
        """Collect metrics and return structured data."""
        pass

    def add_metadata(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Add common metadata to metrics."""
        return {
            "timestamp": time.time(),
            "hostname": self.hostname,
            "monitor_name": self.name,
            "metrics": metrics,
        }
