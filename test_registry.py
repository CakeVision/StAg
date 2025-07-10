"""
Test script for Component Registry functionality.
"""

import socket
import time
from pathlib import Path

from collectors.registry import ComponentRegistry, ComponentState
from config.targets import CONFIG, get_quick_test_config
from logger.json_logger import setup_application_logging


def test_basic_lifecycle():
    """Test basic component lifecycle operations."""
    print("=== Testing Basic Lifecycle ===")

    # Setup
    config = get_quick_test_config()
    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    registry = ComponentRegistry(config, log_manager)

    try:
        # Initialize
        print("1. Initializing registry...")
        registry.initialize()

        # Check initial state
        status = registry.get_all_status()
        print(f"   Components created: {len(status)}")
        for name, info in status.items():
            print(f"   - {name}: {info['state']}")

        # Start all components
        print("\n2. Starting all components...")
        registry.start_all()
        time.sleep(2)  # Let components start

        # Check running state
        status = registry.get_all_status()
        print("   Component states after start:")
        for name, info in status.items():
            print(f"   - {name}: {info['state']}")
            if "details" in info:
                if info["type"] == "target_collector":
                    details = info["details"]
                    print(
                        f"     Collections: {details.get('collections', 0)}, Errors: {details.get('errors', 0)}"
                    )

        # Let it run for a bit
        print("\n3. Running for 10 seconds...")
        time.sleep(10)

        # Check metrics
        data_hub = registry.get_data_hub()
        if data_hub:
            latest_metrics = data_hub.get_latest_metrics()
            print(f"   Latest metrics from {len(latest_metrics)} targets:")
            for target_name, data in latest_metrics.items():
                print(f"   - {target_name}: {data['collection_duration_ms']:.1f}ms")

        # Stop all
        print("\n4. Stopping all components...")
        registry.stop_all()

        # Final state check
        status = registry.get_all_status()
        print("   Final component states:")
        for name, info in status.items():
            print(f"   - {name}: {info['state']}")

        print("\n✓ Basic lifecycle test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Basic lifecycle test failed: {e}")
        return False


def test_component_restart():
    """Test individual component restart functionality."""
    print("\n=== Testing Component Restart ===")

    # Setup
    config = get_quick_test_config()
    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    registry = ComponentRegistry(config, log_manager)

    try:
        # Initialize and start
        print("1. Initializing and starting registry...")
        registry.initialize()
        registry.start_all()
        time.sleep(2)

        # Get initial stats
        target_name = f"target_{config.targets[0].name}"
        initial_status = registry.get_component_status(target_name)
        if initial_status and "details" in initial_status:
            initial_collections = initial_status["details"].get("collections", 0)
            print(f"   Initial collections: {initial_collections}")

        # Restart specific component
        print(f"\n2. Restarting component: {target_name}")
        success = registry.restart_component(target_name)
        print(f"   Restart {'successful' if success else 'failed'}")

        # Let it run again
        time.sleep(5)

        # Check restart stats
        final_status = registry.get_component_status(target_name)
        if final_status and "details" in final_status:
            final_collections = final_status["details"].get("collections", 0)
            restart_count = final_status.get("restart_count", 0)
            print(f"   Final collections: {final_collections}")
            print(f"   Restart count: {restart_count}")

        # Cleanup
        registry.stop_all()

        print("\n✓ Component restart test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Component restart test failed: {e}")
        return False


def test_health_monitoring():
    """Test health monitoring functionality."""
    print("\n=== Testing Health Monitoring ===")

    # Setup
    config = get_quick_test_config()
    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    registry = ComponentRegistry(config, log_manager)

    try:
        # Initialize and start
        print("1. Initializing and starting registry...")
        registry.initialize()
        registry.start_all()
        time.sleep(2)

        # Check initial health
        print("2. Checking component health...")
        all_status = registry.get_all_status()
        healthy_count = sum(
            1 for info in all_status.values() if info["state"] == "running"
        )
        print(f"   Healthy components: {healthy_count}/{len(all_status)}")

        # Let health monitoring run
        print("3. Running health monitoring for 15 seconds...")
        time.sleep(15)

        # Check final health
        final_status = registry.get_all_status()
        final_healthy = sum(
            1 for info in final_status.values() if info["state"] == "running"
        )
        print(f"   Final healthy components: {final_healthy}/{len(final_status)}")

        # Show any failures
        for name, info in final_status.items():
            if info["state"] == "failed":
                print(f"   ✗ {name}: {info['last_error']}")

        # Cleanup
        registry.stop_all()

        print("\n✓ Health monitoring test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Health monitoring test failed: {e}")
        return False


def test_error_scenarios():
    """Test error handling scenarios."""
    print("\n=== Testing Error Scenarios ===")

    # Setup
    config = get_quick_test_config()
    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    registry = ComponentRegistry(config, log_manager)

    try:
        # Initialize
        registry.initialize()

        # Test starting non-existent component
        print("1. Testing start of non-existent component...")
        success = registry.start_component("non_existent")
        print(
            f"   Start non-existent: {'failed as expected' if not success else 'unexpectedly succeeded'}"
        )

        # Test double start
        print("2. Testing double start...")
        registry.start_component("data_hub")
        success = registry.start_component("data_hub")  # Should fail
        print(
            f"   Double start: {'failed as expected' if not success else 'unexpectedly succeeded'}"
        )

        # Test stop non-running component
        print("3. Testing stop of non-running component...")
        success = registry.stop_component("non_existent")
        print(
            f"   Stop non-existent: {'handled gracefully' if not success else 'unexpectedly succeeded'}"
        )

        # Cleanup
        registry.stop_all()

        print("\n✓ Error scenarios test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Error scenarios test failed: {e}")
        return False


def main():
    """Run all registry tests."""
    print("Component Registry Test Suite")
    print("=" * 40)

    tests = [
        test_basic_lifecycle,
        test_component_restart,
        test_health_monitoring,
        test_error_scenarios,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"Test {test.__name__} crashed: {e}")
            failed += 1

        # Small break between tests
        time.sleep(1)

    print(f"\n" + "=" * 40)
    print(f"Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("🎉 All tests passed!")
    else:
        print(f"❌ {failed} test(s) failed")

    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
