"""
Time-series storage with configurable time buckets for historical metrics.
"""

import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config.time_series import AggregationMethod, TimeSeriesConfig
from logger.json_logger import LoggerManager
from monitors.time_metric_bucket import TimeMetricBucket


class TimeSeriesStorage:
    def __init__(
        self, config: TimeSeriesConfig, logger_manager: Optional[LoggerManager] = None
    ):
        self.config: TimeSeriesConfig = config
        self.logger = (
            logger_manager.get_component_logger("time_series")
            if logger_manager
            else None
        )

        # Storage: {target_name: {bucket_time: TimeMetricBucket}}
        self._buckets: Dict[str, Dict[float, TimeMetricBucket]] = defaultdict(dict)
        self._lock: threading.RLock = threading.RLock()

        # Cleanup management
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown_event: threading.Event = threading.Event()
        self._running: bool = False

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        if self.logger:
            self.logger.log_system_event(
                "startup",
                f"Time-series storage started with {self.config.bucket_size_seconds}s buckets",
            )

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return

        self._shutdown_event.set()
        self._running = False

        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=timeout)

        if self.logger:
            total_buckets: int = sum(len(buckets) for buckets in self._buckets.values())
            self.logger.log_system_event(
                "shutdown", f"Time-series storage stopped with {total_buckets} buckets"
            )

    def store_metrics(
        self,
        target_name: str,
        target_type: str,
        timestamp: float,
        metrics: Dict[str, Any],
    ) -> None:
        bucket_time: float = self._get_bucket_time(timestamp)

        with self._lock:
            target_buckets: Dict[float, MetricBucket] = self._buckets[target_name]

            if bucket_time in target_buckets:
                self._update_bucket(target_buckets[bucket_time], timestamp, metrics)
            else:
                bucket = MetricBucket(
                    bucket_time=bucket_time,
                    target_name=target_name,
                    target_type=target_type,
                    metrics=metrics.copy(),
                    sample_count=1,
                    first_timestamp=timestamp,
                    last_timestamp=timestamp,
                )
                target_buckets[bucket_time] = bucket

                if len(target_buckets) > self.config.max_buckets_per_target:
                    self._cleanup_old_buckets(target_name)

    def get_latest_metrics(self, target_name: str) -> Optional[MetricBucket]:
        with self._lock:
            target_buckets: Dict[float, MetricBucket] = self._buckets.get(
                target_name, {}
            )
            if not target_buckets:
                return None

            latest_time: float = max(target_buckets.keys())
            return target_buckets[latest_time]

    def get_metrics_at_time(
        self, target_name: str, timestamp: float
    ) -> Optional[MetricBucket]:
        bucket_time: float = self._get_bucket_time(timestamp)

        with self._lock:
            target_buckets: Dict[float, MetricBucket] = self._buckets.get(
                target_name, {}
            )
            return target_buckets.get(bucket_time)

    def get_metrics_range(
        self, target_name: str, start_time: float, end_time: float
    ) -> List[MetricBucket]:
        with self._lock:
            target_buckets: Dict[float, MetricBucket] = self._buckets.get(
                target_name, {}
            )

            result: List[MetricBucket] = []
            for bucket_time, bucket in target_buckets.items():
                if start_time <= bucket_time <= end_time:
                    result.append(bucket)

            result.sort(key=lambda b: b.bucket_time)
            return result

    def aggregate_over_window(
        self,
        target_name: str,
        start_time: float,
        end_time: float,
        metric_path: str,
        method: Optional[AggregationMethod] = None,
    ) -> Optional[float]:
        if method is None:
            method = self.config.default_aggregation

        buckets: List[MetricBucket] = self.get_metrics_range(
            target_name, start_time, end_time
        )
        if not buckets:
            return None

        # Extract metric values
        values: List[float] = []
        for bucket in buckets:
            value = self._get_nested_metric(bucket.metrics, metric_path)
            if value is not None and isinstance(value, (int, float)):
                values.append(float(value))

        if not values:
            return None

        # Apply aggregation
        if method == AggregationMethod.LAST:
            return values[-1]
        elif method == AggregationMethod.FIRST:
            return values[0]
        elif method == AggregationMethod.AVG:
            return sum(values) / len(values)
        elif method == AggregationMethod.MIN:
            return min(values)
        elif method == AggregationMethod.MAX:
            return max(values)
        elif method == AggregationMethod.COUNT:
            return float(len(values))
        else:
            return None

    def get_all_targets(self) -> List[str]:
        with self._lock:
            return list(self._buckets.keys())

    def get_target_stats(self, target_name: str) -> Dict[str, Any]:
        with self._lock:
            target_buckets: Dict[float, MetricBucket] = self._buckets.get(
                target_name, {}
            )
            if not target_buckets:
                return {}

            bucket_times: List[float] = list(target_buckets.keys())
            total_samples: int = sum(
                bucket.sample_count for bucket in target_buckets.values()
            )

            return {
                "bucket_count": len(target_buckets),
                "total_samples": total_samples,
                "earliest_time": min(bucket_times),
                "latest_time": max(bucket_times),
                "time_span_seconds": max(bucket_times) - min(bucket_times)
                if bucket_times
                else 0,
            }

    def _get_bucket_time(self, timestamp: float) -> float:
        return (
            int(timestamp) // self.config.bucket_size_seconds
        ) * self.config.bucket_size_seconds

    def _update_bucket(
        self, bucket: MetricBucket, timestamp: float, metrics: Dict[str, Any]
    ) -> None:
        bucket.sample_count += 1
        bucket.last_timestamp = timestamp

        if bucket.first_timestamp is None or timestamp < bucket.first_timestamp:
            bucket.first_timestamp = timestamp

        # For now, just use LAST aggregation (replace metrics)
        # TODO: Implement proper aggregation based on config
        bucket.metrics = metrics.copy()

    def _get_nested_metric(self, metrics: Dict[str, Any], path: str) -> Any:
        parts: List[str] = path.split(".")
        current: Any = metrics

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _cleanup_old_buckets(self, target_name: str) -> None:
        target_buckets: Dict[float, MetricBucket] = self._buckets[target_name]

        # Remove buckets beyond retention time
        current_time: float = time.time()
        cutoff_time: float = current_time - self.config.retention_seconds

        to_remove: List[float] = [
            bucket_time
            for bucket_time in target_buckets.keys()
            if bucket_time < cutoff_time
        ]

        for bucket_time in to_remove:
            del target_buckets[bucket_time]

        # If still too many buckets, remove oldest ones
        if len(target_buckets) > self.config.max_buckets_per_target:
            sorted_times: List[float] = sorted(target_buckets.keys())
            excess_count: int = len(target_buckets) - self.config.max_buckets_per_target

            for bucket_time in sorted_times[:excess_count]:
                del target_buckets[bucket_time]

        if self.logger and to_remove:
            self.logger.log_system_event(
                "cleanup", f"Cleaned up {len(to_remove)} old buckets for {target_name}"
            )

    def _cleanup_loop(self) -> None:
        while not self._shutdown_event.wait(
            timeout=self.config.cleanup_interval_seconds
        ):
            try:
                self._cleanup_all_targets()
            except Exception as e:
                if self.logger:
                    self.logger.log_error("Error during cleanup", e)

    def _cleanup_all_targets(self) -> None:
        with self._lock:
            for target_name in list(self._buckets.keys()):
                self._cleanup_old_buckets(target_name)

                # Remove targets with no buckets
                if not self._buckets[target_name]:
                    del self._buckets[target_name]
