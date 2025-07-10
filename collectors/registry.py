"""
Component registry for managing monitoring components with supervisor integration.
"""

import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from collectors.data_hub import DataHub
from collectors.target_thread import TargetThread
from config.components import MonitoringConfig, Target
from logger.json_logger import LoggerManager


class ComponentState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class ComponentInfo:
    def __init__(self, name: str, component_type: str, instance: Any):
        self.name = name
        self.component_type = component_type
        self.instance = instance
        self.state = ComponentState.STOPPED
        self.start_time: Optional[float] = None
        self.stop_time: Optional[float] = None
        self.restart_count = 0
        self.last_error: Optional[str] = None
        self.health_check: Optional[Callable[[], bool]] = None


class ComponentRegistry:
    def __init__(self, config: MonitoringConfig, logger_manager: LoggerManager):
        self.config = config
        self.logger_manager = logger_manager
        self.logger = logger_manager.get_component_logger("registry")

        # Component storage
        self._components: Dict[str, ComponentInfo] = {}
        self._lock = threading.RLock()

        # Core components
        self._data_hub: Optional[DataHub] = None

        # Health monitoring
        self._health_thread: Optional[threading.Thread] = None
        self._health_interval = 30.0
        self._shutdown_event = threading.Event()

    def initialize(self) -> None:
        """Initialize registry and create core components."""
        with self._lock:
            self.logger.log_system_event(
                "initialize", "Initializing component registry"
            )

            # Create and register DataHub
            self._create_data_hub()

            # Create target collectors
            self._create_target_collectors()

            # Start health monitoring
            self._start_health_monitoring()

            self.logger.log_system_event(
                "initialize_complete",
                f"Registry initialized with {len(self._components)} components",
            )

    def start_all(self) -> None:
        """Start all registered components."""
        with self._lock:
            self.logger.log_system_event("start_all", "Starting all components")

            # Start DataHub first
            if self._data_hub:
                self.start_component("data_hub")

            # Start all target collectors
            for name, info in self._components.items():
                if (
                    info.component_type == "target_collector"
                    and info.state == ComponentState.STOPPED
                ):
                    self.start_component(name)

    def stop_all(self, timeout: float = 10.0) -> None:
        """Stop all components gracefully."""
        with self._lock:
            self.logger.log_system_event("stop_all", "Stopping all components")

            # Signal shutdown
            self._shutdown_event.set()

            # Stop target collectors first
            for name, info in self._components.items():
                if (
                    info.component_type == "target_collector"
                    and info.state == ComponentState.RUNNING
                ):
                    self.stop_component(name, timeout=5.0)

            # Stop DataHub last
            if self._data_hub:
                self.stop_component("data_hub", timeout=5.0)

            # Stop health monitoring
            if self._health_thread:
                self._health_thread.join(timeout=5.0)

    def start_component(self, name: str) -> bool:
        """Start a specific component."""
        with self._lock:
            info = self._components.get(name)
            if not info:
                self.logger.log_system_event(
                    "component_not_found", f"Component {name} not found", level=40
                )
                return False

            if info.state != ComponentState.STOPPED:
                self.logger.log_system_event(
                    "component_not_stopped",
                    f"Component {name} not in stopped state",
                    level=40,
                )
                return False

            try:
                info.state = ComponentState.STARTING
                info.start_time = time.time()

                # Start the component based on its type
                if info.component_type == "data_hub":
                    info.instance.start()
                elif info.component_type == "target_collector":
                    info.instance.start()
                else:
                    raise ValueError(f"Unknown component type: {info.component_type}")

                info.state = ComponentState.RUNNING
                info.last_error = None

                self.logger.log_system_event(
                    "component_started",
                    f"Started component {name}",
                    component_type=info.component_type,
                )
                return True

            except Exception as e:
                info.state = ComponentState.FAILED
                info.last_error = str(e)
                self.logger.log_error(f"Failed to start component {name}", e)
                return False

    def stop_component(self, name: str, timeout: float = 5.0) -> bool:
        """Stop a specific component."""
        with self._lock:
            info = self._components.get(name)
            if not info:
                return False

            if info.state != ComponentState.RUNNING:
                return True

            try:
                info.state = ComponentState.STOPPING

                # Stop the component based on its type
                if info.component_type == "data_hub":
                    info.instance.stop(timeout=timeout)
                elif info.component_type == "target_collector":
                    info.instance.stop_gracefully(timeout=timeout)

                info.state = ComponentState.STOPPED
                info.stop_time = time.time()

                self.logger.log_system_event(
                    "component_stopped",
                    f"Stopped component {name}",
                    component_type=info.component_type,
                )
                return True

            except Exception as e:
                info.state = ComponentState.FAILED
                info.last_error = str(e)
                self.logger.log_error(f"Failed to stop component {name}", e)
                return False

    def restart_component(self, name: str, timeout: float = 10.0) -> bool:
        """Restart a specific component."""
        with self._lock:
            info = self._components.get(name)
            if not info:
                return False

            self.logger.log_system_event(
                "component_restart", f"Restarting component {name}"
            )

            # Stop first
            if info.state == ComponentState.RUNNING:
                if not self.stop_component(name, timeout=timeout / 2):
                    return False

            # Recreate component if it's a target collector
            if info.component_type == "target_collector":
                self._recreate_target_collector(name)

            # Start again
            success = self.start_component(name)
            if success:
                info.restart_count += 1

            return success

    def get_component_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific component."""
        with self._lock:
            info = self._components.get(name)
            if not info:
                return None

            status = {
                "name": info.name,
                "type": info.component_type,
                "state": info.state.value,
                "start_time": info.start_time,
                "stop_time": info.stop_time,
                "restart_count": info.restart_count,
                "last_error": info.last_error,
            }

            # Add component-specific status
            if hasattr(info.instance, "get_status"):
                status["details"] = info.instance.get_status()

            return status

    def get_all_status(self) -> Dict[str, Any]:
        """Get status of all components."""
        with self._lock:
            return {
                name: self.get_component_status(name)
                for name in self._components.keys()
            }

    def get_data_hub(self) -> Optional[DataHub]:
        """Get the DataHub instance."""
        return self._data_hub

    def _create_data_hub(self) -> None:
        """Create and register the DataHub."""
        hub_config = self.config.data_hub
        self._data_hub = DataHub(
            config_name=hub_config.name,
            max_queue_size=hub_config.max_queue_size,
            logger_manager=self.logger_manager,
        )

        info = ComponentInfo("data_hub", "data_hub", self._data_hub)
        info.health_check = lambda: self._data_hub._running
        self._components["data_hub"] = info

    def _create_target_collectors(self) -> None:
        """Create and register target collector threads."""
        if not self._data_hub:
            raise RuntimeError("DataHub must be created before target collectors")

        enabled_targets = self.config.get_enabled_targets()
        for target in enabled_targets:
            self._create_target_collector(target)

    def _create_target_collector(self, target: Target) -> None:
        """Create a single target collector."""
        thread = TargetThread(target, self._data_hub, self.logger_manager)

        info = ComponentInfo(f"target_{target.name}", "target_collector", thread)
        info.health_check = lambda t=thread: t.is_alive()
        self._components[f"target_{target.name}"] = info

    def _recreate_target_collector(self, name: str) -> None:
        """Recreate a target collector (for restart scenarios)."""
        info = self._components.get(name)
        if not info or info.component_type != "target_collector":
            return

        # Find the target config
        target_name = name.replace("target_", "")
        target = None
        for t in self.config.targets:
            if t.name == target_name:
                target = t
                break

        if target:
            # Create new thread instance
            new_thread = TargetThread(target, self._data_hub, self.logger_manager)
            info.instance = new_thread
            info.health_check = lambda t=new_thread: t.is_alive()

    def _start_health_monitoring(self) -> None:
        """Start background health monitoring."""
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop, daemon=True
        )
        self._health_thread.start()

    def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        while not self._shutdown_event.wait(timeout=self._health_interval):
            self._check_component_health()

    def _check_component_health(self) -> None:
        """Check health of all components."""
        with self._lock:
            for name, info in self._components.items():
                if info.state == ComponentState.RUNNING and info.health_check:
                    try:
                        if not info.health_check():
                            self.logger.log_system_event(
                                "component_unhealthy",
                                f"Component {name} failed health check",
                                level=40,
                            )
                            info.state = ComponentState.FAILED
                    except Exception as e:
                        self.logger.log_error(f"Health check failed for {name}", e)
