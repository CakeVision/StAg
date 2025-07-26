"""
Time-series storage configuration components.
"""

from dataclasses import dataclass
from enum import Enum


class AggregationMethod(Enum):
    LAST = "last"
    FIRST = "first"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"


@dataclass
class TimeSeriesConfig:
    bucket_size_seconds: int = 60
    retention_seconds: int = 3600
    cleanup_interval_seconds: int = 300
    max_buckets_per_target: int = 1000
    default_aggregation: AggregationMethod = AggregationMethod.LAST
