"""
Simple testing configuration for homelab monitoring development.

Uses the composite pattern with minimal targets to keep development focused.
Perfect for testing concurrent collection, DataHub integration, and logging.
"""

from config.components import (
    DataHubConfig,
    MonitoringConfig,
    SSHConfig,
    SystemConfig,
    Target,
)

# === LEAF CONFIGS ===

# Local system monitoring - always works
local_system = SystemConfig(
    name="local-system",
    description="Local development machine",
    enabled=True,
    collect_cpu=True,
    collect_memory=True,
    collect_disk=True,
    collect_network=True,
    collect_load=True,
    tags={"environment": "dev", "role": "development"},
)

# Test VM - adjust IP to your setup
test_vm_ssh = SSHConfig(
    name="test-vm-ssh",
    description="Test VM for remote monitoring",
    host="192.168.1.100",  # Change this to your VM's IP
    port=22,
    user="monitoring",  # Change to your SSH user
    timeout=10,
    enabled=True,
    tags={"environment": "test", "role": "vm"},
)

# Data hub configuration - tuned for development
dev_data_hub = DataHubConfig(
    name="dev-data-hub",
    description="Development data aggregation hub",
    enabled=True,
    max_queue_size=100,  # Small for development
    queue_timeout=2.0,  # Quick timeout for testing
    storage_type="memory",  # Simple memory storage
    retention_seconds=300,  # 5 minutes retention
    enable_prometheus_cache=True,
    prometheus_update_interval=5.0,
    enable_json_logging=True,
    log_all_metrics=False,  # Keep logs clean during dev
    tags={"component": "data-hub"},
)

# === COMPOSITE CONFIGS ===

# Simple targets for testing
test_targets = [
    # Always-working local target
    Target(
        name="localhost",
        description="Local system metrics for development",
        type="system",
        enabled=True,
        interval=15,  # Fast collection for development
        metrics=["cpu", "memory", "disk"],
        system=local_system,
        tags={"priority": "high", "location": "local"},
    ),
    # Optional VM target - disable if no VM available
    Target(
        name="test-vm",
        description="Test VM for remote collection",
        type="ssh",
        enabled=False,  # Set to True when you have a test VM ready
        interval=30,  # Slower for remote
        metrics=["cpu", "memory"],
        ssh=test_vm_ssh,
        tags={"priority": "medium", "location": "remote"},
    ),
]

# === ROOT CONFIGURATION ===

CONFIG = MonitoringConfig(
    name="homelab-dev-config",
    description="Simple development configuration for testing",
    enabled=True,
    # Development-friendly settings
    default_interval=20,
    max_workers=3,  # Small for development
    log_level="DEBUG",  # Verbose logging
    # Service ports - avoid conflicts
    prometheus_enabled=True,
    prometheus_port=8000,  # Standard port from .envrc
    health_enabled=True,
    health_port=8001,  # Health check port
    # Composite components
    data_hub=dev_data_hub,
    targets=test_targets,
    tags={"environment": "development", "version": "0.1.0", "purpose": "testing"},
)

# === DEVELOPMENT UTILITIES ===


def get_quick_test_config() -> MonitoringConfig:
    """Get a minimal config with just localhost for quick testing."""
    quick_hub = DataHubConfig(
        name="quick-hub",
        max_queue_size=50,
        retention_seconds=60,  # 1 minute
    )

    quick_target = Target(
        name="localhost-quick",
        type="system",
        interval=5,  # Very fast for quick tests
        system=SystemConfig(name="quick-system"),
        tags={"test": "quick"},
    )

    return MonitoringConfig(
        name="quick-test",
        max_workers=1,
        log_level="INFO",
        data_hub=quick_hub,
        targets=[quick_target],
    )


def get_stress_test_config() -> MonitoringConfig:
    """Get a config with multiple targets for stress testing."""
    stress_hub = DataHubConfig(
        name="stress-hub", max_queue_size=1000, retention_seconds=3600
    )

    # Create multiple local targets with different intervals
    stress_targets = []
    for i in range(5):
        target = Target(
            name=f"stress-target-{i}",
            type="system",
            interval=10 + (i * 5),  # Staggered intervals
            system=SystemConfig(name=f"stress-system-{i}"),
            tags={"test": "stress", "index": str(i)},
        )
        stress_targets.append(target)

    return MonitoringConfig(
        name="stress-test",
        max_workers=10,
        log_level="WARNING",  # Reduce log noise
        data_hub=stress_hub,
        targets=stress_targets,
    )


def print_config_summary(config: MonitoringConfig = CONFIG):
    """Print a summary of the current configuration."""
    print(f"Configuration Summary: {config.name}")
    print("-" * 40)

    # Basic info
    print(f"Description: {config.description}")
    print(f"Log Level: {config.log_level}")
    print(f"Max Workers: {config.max_workers}")
    print(
        f"Prometheus: {config.prometheus_port if config.prometheus_enabled else 'disabled'}"
    )

    # Data hub info
    hub = config.data_hub
    print(f"\nData Hub: {hub.name}")
    print(f"  Queue Size: {hub.max_queue_size}")
    print(f"  Storage: {hub.storage_type}")
    print(f"  Retention: {hub.retention_seconds}s")

    # Targets info
    enabled_targets = config.get_enabled_targets()
    print(f"\nTargets: {len(enabled_targets)} enabled / {len(config.targets)} total")

    for target in config.targets:
        status = "[ENABLED]" if target.enabled else "[DISABLED]"
        service_config = target.get_service_config() if target.enabled else None
        service_type = service_config.__class__.__name__ if service_config else "N/A"

        print(
            f"  {status} {target.name} ({target.type}, {target.interval}s) -> {service_type}"
        )
        if target.tags:
            tag_str = ", ".join([f"{k}={v}" for k, v in target.tags.items()])
            print(f"      Tags: {tag_str}")

    # Validation
    errors = config.validate()
    print(f"\nValidation: {'PASS' if not errors else f'FAIL ({len(errors)} errors)'}")
    for error in errors:
        print(f"  - {error}")


def enable_vm_target(vm_ip: str, vm_user: str = "monitoring"):
    """Helper to quickly enable the VM target with your settings."""
    CONFIG.targets[1].enabled = True
    CONFIG.targets[1].ssh.host = vm_ip
    CONFIG.targets[1].ssh.user = vm_user
    print(f"Enabled VM target: {vm_user}@{vm_ip}")


def disable_all_remote_targets():
    """Disable all non-local targets for offline development."""
    for target in CONFIG.targets:
        if target.type != "system":
            target.enabled = False
    print("Disabled all remote targets for offline development")


# === EXAMPLE USAGE ===

if __name__ == "__main__":
    print("Homelab Monitor - Development Configuration")
    print_config_summary()

    print("\nDevelopment Helpers:")
    print("  CONFIG                     - Main development config")
    print("  get_quick_test_config()    - Minimal config for quick tests")
    print("  get_stress_test_config()   - Multiple targets for stress testing")
    print("  enable_vm_target(ip, user) - Quick VM setup")
    print("  disable_all_remote_targets() - Offline development")

    print("\nConfig Tree:")
    print(CONFIG.get_config_tree())

    # Show how to use different configs
    print("\nQuick Test Example:")
    quick = get_quick_test_config()
    print(f"  Targets: {len(quick.targets)}")
    print(f"  Interval: {quick.targets[0].interval}s")
    print(f"  Workers: {quick.max_workers}")
