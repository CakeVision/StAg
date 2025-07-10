"""
Enhanced composite configuration system for homelab monitoring.

Implements the composite pattern where:
- Component: Base interface for all config objects
- Leaf: Individual service configs (SSH, Docker, System)
- Composite: Configs that contain other configs (Target, MonitoringConfig)

This allows treating individual configs and groups uniformly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union


class ConfigComponent(ABC):
    """Base component interface for composite pattern."""

    @abstractmethod
    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        pass

    @abstractmethod
    def get_config_tree(self, indent: int = 0) -> str:
        """Get string representation of config tree."""
        pass

    @abstractmethod
    def find_configs_by_type(self, config_type: type) -> List["ConfigComponent"]:
        """Find all configs of a specific type in the tree."""
        pass

    @abstractmethod
    def get_all_leaf_configs(self) -> List["ConfigComponent"]:
        """Get all leaf configs (no children)."""
        pass


@dataclass
class BaseConfig(ConfigComponent):
    """Base configuration with common fields and composite interface."""

    enabled: bool = True
    name: str = ""
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """Base validation - override in subclasses."""
        errors = []
        if not self.name:
            errors.append(f"{self.__class__.__name__} missing required 'name' field")
        return errors

    def get_config_tree(self, indent: int = 0) -> str:
        """Default tree representation for leaf configs."""
        prefix = "  " * indent
        status = "✓" if self.enabled else "✗"
        return f"{prefix}{status} {self.__class__.__name__}: {self.name}"

    def find_configs_by_type(self, config_type: type) -> List[ConfigComponent]:
        """Leaf configs only return themselves if they match."""
        return [self] if isinstance(self, config_type) else []

    def get_all_leaf_configs(self) -> List[ConfigComponent]:
        """Leaf configs return themselves."""
        return [self]


# === LEAF CONFIGS ===


@dataclass
class SystemConfig(BaseConfig):
    """Local system monitoring configuration - LEAF."""

    collect_cpu: bool = True
    collect_memory: bool = True
    collect_disk: bool = True
    collect_network: bool = True
    collect_load: bool = True

    def validate(self) -> List[str]:
        errors = super().validate()
        if not any(
            [
                self.collect_cpu,
                self.collect_memory,
                self.collect_disk,
                self.collect_network,
                self.collect_load,
            ]
        ):
            errors.append(f"SystemConfig '{self.name}' has no metrics enabled")
        return errors


@dataclass
class SSHConfig(BaseConfig):
    """SSH connection configuration - LEAF."""

    host: str = "localhost"
    port: int = 22
    user: str = "monitoring"
    key_path: Optional[str] = None
    timeout: int = 10

    def validate(self) -> List[str]:
        errors = super().validate()
        if not self.host:
            errors.append(f"SSHConfig '{self.name}' missing host")
        if not self.user:
            errors.append(f"SSHConfig '{self.name}' missing user")
        if self.port <= 0 or self.port > 65535:
            errors.append(f"SSHConfig '{self.name}' invalid port: {self.port}")
        return errors


@dataclass
class DockerConfig(BaseConfig):
    """Docker connection configuration - LEAF."""

    socket_path: str = "unix:///var/run/docker.sock"
    host: str = "localhost"
    port: int = 2376
    timeout: int = 10
    tls_verify: bool = False

    def validate(self) -> List[str]:
        errors = super().validate()
        if not self.socket_path and not self.host:
            errors.append(
                f"DockerConfig '{self.name}' needs either socket_path or host"
            )
        return errors


@dataclass
class DataHubConfig(BaseConfig):
    """Data aggregation configuration - LEAF."""

    max_queue_size: int = 1000
    queue_timeout: float = 1.0
    storage_type: str = "memory"  # memory, time_buckets, both
    retention_seconds: int = 3600
    enable_prometheus_cache: bool = True
    prometheus_update_interval: float = 5.0
    enable_json_logging: bool = True
    log_all_metrics: bool = False

    def validate(self) -> List[str]:
        errors = super().validate()
        if self.max_queue_size <= 0:
            errors.append(
                f"DataHubConfig '{self.name}' invalid queue size: {self.max_queue_size}"
            )
        if self.storage_type not in ["memory", "time_buckets", "both"]:
            errors.append(
                f"DataHubConfig '{self.name}' invalid storage_type: {self.storage_type}"
            )
        return errors


# === COMPOSITE CONFIGS ===


@dataclass
class CompositeConfig(BaseConfig):
    """Base class for configs that contain other configs."""

    def get_children(self) -> List[ConfigComponent]:
        """Get direct child configs - override in subclasses."""
        return []

    def find_configs_by_type(self, config_type: type) -> List[ConfigComponent]:
        """Recursively find configs of specific type."""
        results = []

        # Check self
        if isinstance(self, config_type):
            results.append(self)

        # Check children recursively
        for child in self.get_children():
            results.extend(child.find_configs_by_type(config_type))

        return results

    def get_all_leaf_configs(self) -> List[ConfigComponent]:
        """Get all leaf configs recursively."""
        leaves = []
        for child in self.get_children():
            leaves.extend(child.get_all_leaf_configs())
        return leaves

    def get_config_tree(self, indent: int = 0) -> str:
        """Get tree representation showing hierarchy."""
        prefix = "  " * indent
        status = "✓" if self.enabled else "✗"
        tree = f"{prefix}{status} {self.__class__.__name__}: {self.name}\n"

        for child in self.get_children():
            tree += child.get_config_tree(indent + 1) + "\n"

        return tree.rstrip()

    def validate(self) -> List[str]:
        """Validate self and all children."""
        errors = super().validate()

        for child in self.get_children():
            errors.extend(child.validate())

        return errors


@dataclass
class Target(CompositeConfig):
    """A monitoring target - COMPOSITE containing service configs."""

    type: str = "system"  # system, ssh, docker
    interval: int = 30
    metrics: List[str] = field(default_factory=lambda: ["cpu", "memory", "disk"])

    # Child configs
    ssh: Optional[SSHConfig] = None
    docker: Optional[DockerConfig] = None
    system: Optional[SystemConfig] = None

    def get_children(self) -> List[ConfigComponent]:
        """Return non-None child configs."""
        children = []
        if self.ssh:
            children.append(self.ssh)
        if self.docker:
            children.append(self.docker)
        if self.system:
            children.append(self.system)
        return children

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

    def validate(self) -> List[str]:
        errors = super().validate()

        # Validate target-specific requirements
        if self.interval <= 0:
            errors.append(f"Target '{self.name}' invalid interval: {self.interval}")

        if self.type not in ["system", "ssh", "docker"]:
            errors.append(f"Target '{self.name}' invalid type: {self.type}")

        # Ensure target has appropriate service config
        try:
            self.get_service_config()
        except ValueError as e:
            errors.append(f"Target '{self.name}': {str(e)}")

        return errors


@dataclass
class MonitoringConfig(CompositeConfig):
    """Top-level config - ROOT COMPOSITE containing everything."""

    # Global settings
    default_interval: int = 30
    max_workers: int = 10
    log_level: str = "INFO"

    # Component settings
    prometheus_enabled: bool = True
    prometheus_port: int = 8080
    health_enabled: bool = True
    health_port: int = 8081

    # Child configs
    data_hub: DataHubConfig = field(
        default_factory=lambda: DataHubConfig(name="main-hub")
    )
    targets: List[Target] = field(default_factory=list)

    def get_children(self) -> List[ConfigComponent]:
        """Return data hub and all targets."""
        children = [self.data_hub]
        children.extend(self.targets)
        return children

    def get_enabled_targets(self) -> List[Target]:
        """Get all enabled targets."""
        return [t for t in self.targets if t.enabled]

    def get_targets_by_type(self, target_type: str) -> List[Target]:
        """Get targets of specific type."""
        return [t for t in self.targets if t.type == target_type and t.enabled]

    def validate(self) -> List[str]:
        errors = super().validate()

        # Validate global settings
        if self.max_workers <= 0:
            errors.append(f"MonitoringConfig invalid max_workers: {self.max_workers}")

        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            errors.append(f"MonitoringConfig invalid log_level: {self.log_level}")

        # Check for duplicate target names
        target_names = [t.name for t in self.targets]
        duplicates = [name for name in target_names if target_names.count(name) > 1]
        if duplicates:
            errors.append(f"MonitoringConfig has duplicate target names: {duplicates}")

        return errors


# === UTILITY FUNCTIONS ===


def create_config_from_dict(data: Dict[str, Any]) -> MonitoringConfig:
    """Create MonitoringConfig from dictionary (for YAML loading)."""
    # This would be implemented to deserialize from YAML/JSON
    # For now, just return a basic config
    return MonitoringConfig(name="loaded-config")


def print_config_analysis(config: MonitoringConfig):
    """Print detailed analysis of configuration."""
    print(f"🔧 Configuration Analysis: {config.name}")
    print("=" * 50)

    # Print tree structure
    print("\n📁 Configuration Tree:")
    print(config.get_config_tree())

    # Print validation results
    print("\n✅ Validation Results:")
    errors = config.validate()
    if errors:
        for error in errors:
            print(f"  ❌ {error}")
    else:
        print("  ✅ All configurations valid!")

    # Print component analysis
    print(f"\n📊 Component Analysis:")
    all_configs = config.get_all_leaf_configs()
    print(f"  Total leaf configs: {len(all_configs)}")

    # Count by type
    type_counts = {}
    for cfg in all_configs:
        cfg_type = cfg.__class__.__name__
        type_counts[cfg_type] = type_counts.get(cfg_type, 0) + 1

    for cfg_type, count in type_counts.items():
        print(f"  {cfg_type}: {count}")

    # Print enabled targets
    enabled_targets = config.get_enabled_targets()
    print(f"\n🎯 Enabled Targets: {len(enabled_targets)}")
    for target in enabled_targets:
        service_config = target.get_service_config()
        print(
            f"  • {target.name} ({target.type}) -> {service_config.__class__.__name__}"
        )


# === EXAMPLE USAGE ===

if __name__ == "__main__":
    # Create a complex configuration using composite pattern

    # Leaf configs
    local_system = SystemConfig(
        name="local-system",
        description="Local system monitoring",
        collect_network=False,  # Disable network for demo
    )

    vm_ssh = SSHConfig(
        name="vm-ssh", host="192.168.1.101", user="monitoring", timeout=15
    )

    docker_local = DockerConfig(name="local-docker", socket_path="/var/run/docker.sock")

    hub_config = DataHubConfig(name="main-hub", max_queue_size=500, storage_type="both")

    # Composite configs (targets)
    targets = [
        Target(
            name="localhost",
            type="system",
            description="Local system metrics",
            interval=30,
            system=local_system,
        ),
        Target(
            name="test-vm",
            type="ssh",
            description="Remote test VM",
            interval=60,
            ssh=vm_ssh,
            tags={"role": "test", "environment": "dev"},
        ),
        Target(
            name="docker-host",
            type="docker",
            description="Local Docker containers",
            interval=45,
            docker=docker_local,
        ),
    ]

    # Root composite
    config = MonitoringConfig(
        name="homelab-monitor",
        description="Complete homelab monitoring setup",
        max_workers=8,
        log_level="DEBUG",
        data_hub=hub_config,
        targets=targets,
    )

    # Demonstrate composite pattern usage
    print_config_analysis(config)

    print(f"\n🔍 Composite Pattern Demonstrations:")

    # Find all SSH configs
    ssh_configs = config.find_configs_by_type(SSHConfig)
    print(f"  SSH configs found: {len(ssh_configs)}")
    for ssh in ssh_configs:
        print(f"    • {ssh.name} -> {ssh.host}:{ssh.port}")

    # Find all system configs
    system_configs = config.find_configs_by_type(SystemConfig)
    print(f"  System configs found: {len(system_configs)}")

    # Get all leaf configs
    leaves = config.get_all_leaf_configs()
    print(f"  Total leaf configurations: {len(leaves)}")

    # Validate entire tree
    errors = config.validate()
    print(f"  Validation errors: {len(errors)}")
