"""
Base classes for component lifecycle and data flow management.
"""

import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from logger.json_logger import LoggerManager
from messaging.queue_manager import QueueManager, get_queue_manager


class ComponentBase(ABC):
    """Base class for component lifecycle management."""

    def __init__(self, name: str):
        self.name = name
        self._running = False
        self._start_time: Optional[float] = None
        self._stop_time: Optional[float] = None
        self._restart_count = 0

    @abstractmethod
    def start(self) -> None:
        """Start the component."""
        pass

    @abstractmethod
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the component."""
        pass

    def restart(self, timeout: float = 10.0) -> bool:
        """Restart the component."""
        try:
            if self._running:
                self.stop(timeout=timeout / 2)

            self.start()
            self._restart_count += 1
            return True
        except Exception:
            return False

    def is_running(self) -> bool:
        """Check if component is running."""
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """Get component status."""
        return {
            "name": self.name,
            "running": self._running,
            "start_time": self._start_time,
            "stop_time": self._stop_time,
            "restart_count": self._restart_count,
        }


class DataProducer:
    """Mixin for components that produce data."""

    def __init__(self, component_name: str, queue_manager: QueueManager):
        self.component_name = component_name
        self.queue_manager = queue_manager
        self.output_queues: List[str] = []
        self.consumers: List["DataConsumer"] = []

    def add_consumer(self, consumer: "DataConsumer") -> str:
        """Add a consumer and create queue automatically."""
        consumer_name = getattr(consumer, "name", str(consumer))

        # Create queue for this producer -> consumer connection
        queue_id = self._create_output_queue(f"to_{consumer_name}")

        # Wire up the connection
        consumer._add_input_queue(queue_id)
        self.consumers.append(consumer)

        # Set friendly name
        queue_name = f"{self.component_name}_to_{consumer_name}"
        self.queue_manager.set_queue_name(queue_id, queue_name)

        return queue_id

    def _create_output_queue(self, connection_name: str) -> str:
        """Create an output queue."""
        queue_name = f"{self.component_name}_{connection_name}"
        queue_id = self.queue_manager.create_queue(name=queue_name)
        self.output_queues.append(queue_id)
        return queue_id

    def _publish_data(self, data: Any) -> bool:
        """Publish data to all output queues."""
        success = True
        for queue_id in self.output_queues:
            queue_obj = self.queue_manager.get_queue(queue_id)
            if queue_obj:
                if not queue_obj.publish(data):
                    success = False
        return success

    def notify_consumers(self, event: str, data: Any = None):
        """Notify consumers of events (restarts, etc.)."""
        for consumer in self.consumers:
            if hasattr(consumer, "on_source_event"):
                consumer.on_source_event(self, event, data)


class DataConsumer:
    """Mixin for components that consume data."""

    def __init__(self, component_name: str, queue_manager: QueueManager):
        self.component_name = component_name
        self.queue_manager = queue_manager
        self.input_queues: List[str] = []
        self.sources: List["DataProducer"] = []
        self._waiting_for_sources = False

    def add_source(self, source: "DataProducer") -> str:
        """Add a source and create queue automatically."""
        source_name = getattr(source, "name", str(source))

        # Create queue for this source -> consumer connection
        queue_id = self._create_input_queue(f"from_{source_name}")

        # Wire up the connection
        source._add_output_queue(queue_id)
        self.sources.append(source)

        # Set friendly name
        queue_name = f"{source_name}_to_{self.component_name}"
        self.queue_manager.set_queue_name(queue_id, queue_name)

        return queue_id

    def _create_input_queue(self, connection_name: str) -> str:
        """Create an input queue."""
        queue_name = f"{self.component_name}_{connection_name}"
        queue_id = self.queue_manager.create_queue(name=queue_name)
        self.input_queues.append(queue_id)
        return queue_id

    def _add_input_queue(self, queue_id: str):
        """Add an existing input queue."""
        if queue_id not in self.input_queues:
            self.input_queues.append(queue_id)

    def _consume_data(self, timeout: float = 0.1) -> List[Any]:
        """Consume data from all input queues."""
        if self._waiting_for_sources:
            return []

        data_items = []
        for queue_id in self.input_queues:
            queue_obj = self.queue_manager.get_queue(queue_id)
            if queue_obj:
                try:
                    data = queue_obj.consume(timeout=timeout)
                    data_items.append(data)
                except Exception:  # queue.Empty or other errors
                    continue

        return data_items

    def on_source_event(self, source: "DataProducer", event: str, data: Any = None):
        """Handle events from sources."""
        if event == "restart":
            self._waiting_for_sources = True
            # Give source time to restart
            threading.Timer(2.0, self._resume_consumption).start()
        elif event == "ready":
            self._waiting_for_sources = False

    def _resume_consumption(self):
        """Resume consumption after source restart."""
        self._waiting_for_sources = False


class ManagedComponent(ComponentBase, DataProducer, DataConsumer):
    """Component that combines lifecycle management with data flow capabilities."""

    def __init__(
        self,
        name: str,
        queue_manager: Optional[QueueManager] = None,
        logger_manager: Optional[LoggerManager] = None,
    ):
        ComponentBase.__init__(self, name)

        # Get or create queue manager
        if queue_manager is None:
            queue_manager = get_queue_manager("main", logger_manager)

        DataProducer.__init__(self, name, queue_manager)
        DataConsumer.__init__(self, name, queue_manager)

        self.logger = (
            logger_manager.get_component_logger(name) if logger_manager else None
        )

    def start(self) -> None:
        if self._running:
            return

        # Start queue manager
        self.queue_manager.start()

        self._running = True
        self._start_time = time.time()
        self._stop_time = None

        # Notify consumers we're starting
        self.notify_consumers("ready")

        if self.logger:
            self.logger.log_system_event(
                "component_start", f"Component {self.name} started"
            )

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return

        # Notify consumers we're stopping
        self.notify_consumers("stopping")

        self._running = False
        self._stop_time = time.time()

        if self.logger:
            self.logger.log_system_event(
                "component_stop", f"Component {self.name} stopped"
            )

    def restart(self, timeout: float = 10.0) -> bool:
        """Restart with proper consumer notification."""
        try:
            # Notify consumers we're restarting
            self.notify_consumers("restart")

            if self._running:
                self.stop(timeout=timeout / 2)

            self.start()
            self._restart_count += 1

            # Notify consumers we're ready
            self.notify_consumers("ready")

            return True
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to restart component {self.name}", e)
            return False

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update(
            {
                "input_queues": len(self.input_queues),
                "output_queues": len(self.output_queues),
                "sources": len(self.sources),
                "consumers": len(self.consumers),
                "waiting_for_sources": self._waiting_for_sources,
            }
        )
        return status


# Convenience methods for the clean API
def connect_components(producer: DataProducer, *consumers: DataConsumer) -> List[str]:
    """Connect one producer to multiple consumers."""
    queue_ids = []
    for consumer in consumers:
        queue_id = producer.add_consumer(consumer)
        queue_ids.append(queue_id)
    return queue_ids


def create_pipeline(*components) -> None:
    """Create a linear pipeline of components."""
    for i in range(len(components) - 1):
        producer = components[i]
        consumer = components[i + 1]
        producer.add_consumer(consumer)
