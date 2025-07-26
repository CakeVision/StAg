"""
Time-based metric bucket that implements BaseMetrics interface.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from monitors.base import BaseMetrics


@dataclass
class TimeMetricBucket(BaseMetrics):
    """Time bucket containing aggregated metrics."""

    bucket_time: float
    target_name: str
    target_type: str
    metrics: Dict[str, Any]
    sample_count: int = 1
    first_timestamp: Optional[float] = None
    last_timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize bucket including all metadata and metrics."""
        return asdict(self)
