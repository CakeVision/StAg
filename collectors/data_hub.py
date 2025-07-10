"""
Centralized data aggregation hub for thread-safe metric collection.
"""

import queue
import threading
import time
from typing import Any, Dict, Optional

from logger.json_logger import LoggerManager
from monitors.base import BaseMetrics


class DataHub:
    def __init__(
        self,
        config_name: str,
        max_queue_size: int = 1000,
        logger_manager: Optional[LoggerManager] = None,
    ):
        self.config_name = config_name
        self.logger = (
            logger_manager.get_component_logger("data_hub") if logger_manager else None
        )

        # Thread-safe storage
        self._metrics_queue = queue.Queue(maxsize=max_queue_size)
        self._latest_metrics = {}
        self._lock = threading.Lock()

        # Background processor
        self._processor_thread = None
        self._shutdown_event = threading.Event()
        self._running = False

    def start(self):
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._processor_thread = threading.Thread(
            target=self._process_queue, daemon=True
        )
        self._processor_thread.start()

        if self.logger:
            self.logger.log_system_event(
                "startup", f"DataHub '{self.config_name}' started"
            )

    def stop(self, timeout: float = 5.0):
        if not self._running:
            return

        self._shutdown_event.set()
        self._running = False

        if self._processor_thread:
            self._processor_thread.join(timeout=timeout)

        if self.logger:
            self.logger.log_system_event(
                "shutdown", f"DataHub '{self.config_name}' stopped"
            )

    def submit_metrics(
        self,
        target_name: str,
        target_type: str,
        metrics: BaseMetrics,
        collection_time: float,
    ) -> bool:
        if not self._running:
            return False

        try:
            entry = {
                "target_name": target_name,
                "target_type": target_type,
                "collection_time": collection_time,
                "timestamp": time.time(),
                "metrics": metrics.to_dict(),
            }

            self._metrics_queue.put(entry, timeout=1.0)
            return True

        except queue.Full:
            if self.logger:
                self.logger.log_system_event(
                    "queue_full", f"Dropping metrics from {target_name}", level=40
                )
            return False
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to submit metrics from {target_name}", e)
            return False

    def get_latest_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return self._latest_metrics.copy()

    def get_target_metrics(self, target_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest_metrics.get(target_name)

    def _process_queue(self):
        while not self._shutdown_event.is_set():
            try:
                entry = self._metrics_queue.get(timeout=1.0)
                self._handle_entry(entry)
            except queue.Empty:
                continue
            except Exception as e:
                if self.logger:
                    self.logger.log_error("Error processing metrics queue", e)

    def _handle_entry(self, entry: Dict[str, Any]):
        target_name = entry["target_name"]
        target_type = entry["target_type"]

        # Store latest metrics
        with self._lock:
            self._latest_metrics[target_name] = {
                "target_type": target_type,
                "last_updated": entry["timestamp"],
                "collection_duration_ms": entry["collection_time"] * 1000,
                "metrics": entry["metrics"],
            }

        # Log collection
        if self.logger:
            self.logger.log_metric_collection(
                target=target_name,
                target_type=target_type,
                metrics=entry["metrics"],
                duration_ms=entry["collection_time"] * 1000,
                success=True,
            )
