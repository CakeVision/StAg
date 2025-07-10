"""
Configuration components
Composite configuration system for homelab monitoring.

Uses composite pattern: leaf configs (SSH, Docker, System) compose into
Target configs, which compose into the top-level MonitoringConfig.

Like this cause lsp
"""

"""
Future goals:
    - mid-level process nodes for service/transformations integration
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BaseConfig:
    """Base configuration for all components."""

    enabled: bool = True
    name: str = ""
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)


# Leaf configs - actual service configurations
@dataclass
class SSHConfig(BaseConfig):
    """SSH connection configuration."""

    host: str = "localhost"
    port: int = 22
    user: str = "monitoring"
    key_path: Optional[str] = None
    timeout: int = 10


@dataclass
class DockerConfig(BaseConfig):
    """Docker connection configuration."""

    socket_path: str = "unix:///var/run/docker.sock"
    host: str = "localhost"
    port: int = 2376
    timeout: int = 10


@dataclass
class SystemConfig(BaseConfig):
    """Local system monitoring configuration."""

    pass


# Composite configs - contain other configs
@dataclass
class Target(BaseConfig):
    """A monitoring target - composes service configs."""

    type: str = "system"  # system, ssh, docker
    interval: int = 30
    metrics: List[str] = field(default_factory=lambda: ["cpu", "memory", "disk"])

    # Composed service configs
    ssh: Optional[SSHConfig] = None
    docker: Optional[DockerConfig] = None
    system: Optional[SystemConfig] = None

    def get_service_config(self) -> BaseConfig:
        """Get the appropriate service config for this target type."""
        if self.type == "ssh" and self.ssh:
            return self.ssh
        elif self.type == "docker" and self.docker:
            return self.docker
        elif self.type == "system":
            return self.system or SystemConfig(name=f"{self.name}-system")
        else:
            raise ValueError(f"No service config for target type: {self.type}")


@dataclass
class MonitoringConfig(BaseConfig):
    """Top-level config - composes all targets and global settings."""

    # Global monitoring settings
    default_interval: int = 30
    max_workers: int = 10
    log_level: str = "INFO"

    # Prometheus settings
    prometheus_enabled: bool = True
    prometheus_port: int = 8080

    # Health check settings
    health_enabled: bool = True
    health_port: int = 8081

    # Composed targets
    targets: List[Target] = field(default_factory=list)

    def get_enabled_targets(self) -> List[Target]:
        """Get all enabled targets."""
        return [t for t in self.targets if t.enabled]

    def get_targets_by_type(self, target_type: str) -> List[Target]:
        """Get targets of specific type."""
        return [t for t in self.targets if t.type == target_type and t.enabled]
