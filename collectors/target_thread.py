"""
Individual thread for monitoring a specific target.
"""

import threading
import time
from typing import Any, Dict, Optional

from collectors.data_hub import DataHub
from config.components import BaseConfig, DockerConfig, SSHConfig, SystemConfig, Target
from logger.json_logger import LoggerManager
from monitors.base import BaseMonitor
from monitors.systems import SystemMonitor


class TargetThread(threading.Thread):
    def __init__(
        self, target: Target, data_hub: DataHub, logger_manager: LoggerManager
    ) -> None:
        super().__init__(name=f"target-{target.name}", daemon=True)
        self.target: Target = target
        self.data_hub: DataHub = data_hub
        self.logger = logger_manager.get_target_logger(target.name, target.type)

        # Thread control
        self.stop_event: threading.Event = threading.Event()

        # Monitor creation
        self.monitor: BaseMonitor = self._create_monitor()

        # Stats tracking
        self.collection_count: int = 0
        self.error_count: int = 0
        self.last_success_time: Optional[float] = None
        self.last_error_time: Optional[float] = None

    def _create_monitor(self) -> BaseMonitor:
        service_config: BaseConfig = self.target.get_service_config()

        match service_config:
            case SystemConfig():
                return SystemMonitor(self.target.name)
            case SSHConfig():
                raise NotImplementedError("SSH monitoring not yet implemented")
            case DockerConfig():
                raise NotImplementedError("Docker monitoring not yet implemented")
            case _:
                raise ValueError(f"Unknown service config type: {type(service_config)}")

    def run(self) -> None:
        self.logger.log_system_event(
            "thread_start",
            f"Started monitoring {self.target.name}",
            interval=self.target.interval,
        )

        while not self.stop_event.is_set():
            self._collect_once()
            self._wait_for_next_collection()

        self.logger.log_system_event(
            "thread_stop",
            f"Stopped monitoring {self.target.name}",
            collections=self.collection_count,
            errors=self.error_count,
        )

    def _collect_once(self) -> None:
        start_time: float = time.time()

        try:
            metrics = self.monitor.collect_metrics()
            collection_time: float = time.time() - start_time

            success: bool = self.data_hub.submit_metrics(
                self.target.name, self.target.type, metrics, collection_time
            )

            if success:
                self.collection_count += 1
                self.last_success_time = time.time()
            else:
                self._handle_submission_failure()

        except Exception as e:
            self._handle_collection_error(e, time.time() - start_time)

    def _handle_submission_failure(self) -> None:
        self.error_count += 1
        self.last_error_time = time.time()
        self.logger.log_system_event(
            "submission_failed", "Failed to submit metrics to DataHub", level=40
        )

    def _handle_collection_error(
        self, error: Exception, collection_time: float
    ) -> None:
        self.error_count += 1
        self.last_error_time = time.time()
        self.logger.log_error(
            f"Metric collection failed for {self.target.name}",
            error,
            collection_duration_ms=collection_time * 1000,
        )

    def _wait_for_next_collection(self) -> None:
        self.stop_event.wait(timeout=self.target.interval)

    def stop_gracefully(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.is_alive():
            self.join(timeout=timeout)
            if self.is_alive():
                self.logger.log_system_event(
                    "stop_timeout", f"Thread did not stop within {timeout}s", level=40
                )

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.target.name,
            "type": self.target.type,
            "alive": self.is_alive(),
            "collections": self.collection_count,
            "errors": self.error_count,
            "last_success": self.last_success_time,
            "last_error": self.last_error_time,
            "error_rate": self.error_count
            / max(1, self.collection_count + self.error_count),
        }
