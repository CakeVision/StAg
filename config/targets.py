"""
Simple homelab monitoring configuration for development.

Just localhost + 1 VM to keep it minimal while we build the core logic.
"""

from config.components import MonitoringConfig, SSHConfig, SystemConfig, Target

# Simple service configs
local_system = SystemConfig(name="local-system", description="Local system monitoring")

vm_ssh = SSHConfig(
    name="vm-ssh",
    host="192.168.1.101",  # Change this to your VM's IP
    user="monitoring",
    description="SSH config for test VM",
)

# Just two targets for now
targets = [
    Target(
        name="localhost",
        type="system",
        description="Local system metrics",
        system=local_system,
    ),
    Target(
        name="test-vm",
        type="ssh",
        description="Remote test VM",
        ssh=vm_ssh,
        tags={"role": "test"},
    ),
]

# Minimal top-level config
CONFIG = MonitoringConfig(
    name="homelab-monitor-dev",
    description="Development monitoring setup",
    # Simple settings
    default_interval=30,
    max_workers=5,  # Small for development
    log_level="DEBUG",  # Verbose for development
    # Standard ports
    prometheus_port=8080,
    health_port=8081,
    # Our two targets
    targets=targets,
)
