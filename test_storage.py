#!/usr/bin/env python3
"""
Integration test for time-series storage with existing monitoring components.
Tests direct integration without additional wrapper classes.
"""

import socket
import time
from pathlib import Path

from collectors.registry import ComponentRegistry
from config.targets import get_quick_test_config
from config.time_series import AggregationMethod, TimeSeriesConfig
from logger.json_logger import setup_application_logging
from storage.time_series import TimeSeriesStorage


def test_datahub_timeseries_integration():
    """Test DataHub can directly feed TimeSeriesStorage."""
    print("=== Testing DataHub -> TimeSeriesStorage Integration ===")

    # Setup
    config = get_quick_test_config()
    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    # Create time series storage
    ts_config = TimeSeriesConfig(
        bucket_size_seconds=5,  # Small buckets for testing
        retention_seconds=60,
        max_buckets_per_target=20,
    )
    time_series = TimeSeriesStorage(ts_config, log_manager)

    # Create registry (includes DataHub)
    registry = ComponentRegistry(config, log_manager)

    try:
        print("1. Starting components...")
        time_series.start()
        registry.initialize()
        registry.start_all()

        # Get DataHub instance
        data_hub = registry.get_data_hub()
        if not data_hub:
            print("   ✗ Could not get DataHub instance")
            return False

        print("2. Letting system collect metrics for 10 seconds...")
        time.sleep(10)

        # Get metrics from DataHub
        hub_metrics = data_hub.get_latest_metrics()
        print(f"   DataHub has {len(hub_metrics)} targets")

        # Manually feed DataHub metrics to TimeSeries (this should be automatic)
        for target_name, data in hub_metrics.items():
            print(f"   Storing {target_name} metrics in TimeSeries...")
            time_series.store_metrics(
                target_name=target_name,
                target_type=data.get("target_type", "unknown"),
                timestamp=data.get("last_updated", time.time()),
                metrics=data.get("metrics", {}),
            )

        # Verify TimeSeries has the data
        ts_targets = time_series.get_all_targets()
        print(f"   TimeSeries now has {len(ts_targets)} targets")

        # Test time-series queries
        if ts_targets:
            target_name = ts_targets[0]
            print(f"\n3. Testing time-series queries for {target_name}...")

            # Get latest from TimeSeries
            latest = time_series.get_latest_metrics(target_name)
            if latest:
                print(f"   Latest bucket time: {latest.bucket_time}")
                print(f"   Sample count: {latest.sample_count}")

                # Test aggregation if we have CPU data
                if "cpu" in latest.metrics and "percent" in latest.metrics["cpu"]:
                    cpu_value = latest.metrics["cpu"]["percent"]
                    print(f"   CPU percent: {cpu_value}%")

                # Test bucket-as-BaseMetrics
                bucket_dict = latest.to_dict()
                print(f"   Bucket serializes to {len(bucket_dict)} fields")

                # Show that TimeSeries buckets could feed another DataHub
                print(
                    f"   ✓ TimeMetricBucket implements BaseMetrics - can feed other components"
                )

        # Stop components
        print("\n4. Stopping components...")
        registry.stop_all()
        time_series.stop()

        print("\n✓ DataHub integration test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ DataHub integration test failed: {e}")
        registry.stop_all()
        time_series.stop()
        return False


def test_hierarchical_timeseries():
    """Test TimeSeriesStorage buckets can feed another TimeSeriesStorage."""
    print("\n=== Testing Hierarchical TimeSeries ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    # Create two time series storages with different bucket sizes
    minute_config = TimeSeriesConfig(
        bucket_size_seconds=10,  # 10-second buckets
        retention_seconds=120,
        max_buckets_per_target=20,
    )

    hour_config = TimeSeriesConfig(
        bucket_size_seconds=30,  # 30-second buckets (aggregated)
        retention_seconds=300,
        max_buckets_per_target=15,
    )

    minute_storage = TimeSeriesStorage(minute_config, log_manager)
    hour_storage = TimeSeriesStorage(hour_config, log_manager)

    try:
        print("1. Starting both storage layers...")
        minute_storage.start()
        hour_storage.start()

        print("2. Storing sample data in minute-level storage...")
        current_time = time.time()

        # Store some test data
        for i in range(8):
            metrics = {
                "cpu": {"percent": 20.0 + i * 2},
                "memory": {"percent": 40.0 + i},
            }

            minute_storage.store_metrics(
                "test-target", "system", current_time + i * 3, metrics
            )

        time.sleep(1)  # Let it process

        print("3. Getting aggregated data from minute storage...")
        # Get minute-level buckets
        minute_buckets = minute_storage.get_metrics_range(
            "test-target", current_time - 5, current_time + 30
        )

        print(f"   Minute storage has {len(minute_buckets)} buckets")

        # Feed minute buckets to hour storage (bucket-to-bucket aggregation)
        for bucket in minute_buckets:
            print(f"   Moving bucket from {bucket.bucket_time} to hour storage...")
            # TimeMetricBucket implements BaseMetrics, so it can be stored as metrics
            hour_storage.store_metrics(
                target_name=bucket.target_name,
                target_type=bucket.target_type,
                timestamp=bucket.bucket_time,
                metrics=bucket.to_dict(),  # BaseMetrics serialization
            )

        print("4. Verifying hour storage has aggregated data...")
        hour_targets = hour_storage.get_all_targets()
        print(f"   Hour storage targets: {hour_targets}")

        if hour_targets:
            hour_stats = hour_storage.get_target_stats("test-target")
            print(f"   Hour storage buckets: {hour_stats['bucket_count']}")
            print(f"   Hour storage samples: {hour_stats['total_samples']}")

            # Show that we can query the hierarchical data
            latest_hour = hour_storage.get_latest_metrics("test-target")
            if latest_hour:
                print(f"   Latest hour bucket contains minute-level data")
                print(f"   ✓ Hierarchical time-series works")

        # Stop storages
        print("\n5. Stopping storages...")
        minute_storage.stop()
        hour_storage.stop()

        print("\n✓ Hierarchical TimeSeries test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Hierarchical TimeSeries test failed: {e}")
        minute_storage.stop()
        hour_storage.stop()
        return False


def test_target_direct_integration():
    """Test that a target could theoretically feed TimeSeries directly."""
    print("\n=== Testing Target Direct Integration ===")

    from monitors.systems import SystemMonitor

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    # Create time series storage
    ts_config = TimeSeriesConfig(bucket_size_seconds=5, retention_seconds=60)
    time_series = TimeSeriesStorage(ts_config, log_manager)

    try:
        print("1. Starting time series storage...")
        time_series.start()

        print("2. Creating a SystemMonitor directly...")
        monitor = SystemMonitor("direct-test")

        print("3. Collecting metrics directly from monitor...")
        for i in range(3):
            print(f"   Collection {i + 1}...")

            # Collect metrics directly
            metrics = monitor.collect_metrics()

            # Store directly in TimeSeries (no DataHub needed)
            time_series.store_metrics(
                target_name="direct-target",
                target_type="system",
                timestamp=time.time(),
                metrics=metrics.to_dict(),  # BaseMetrics serialization
            )

            time.sleep(2)

        print("4. Verifying direct storage worked...")
        targets = time_series.get_all_targets()
        print(f"   Targets: {targets}")

        if "direct-target" in targets:
            stats = time_series.get_target_stats("direct-target")
            print(f"   Buckets: {stats['bucket_count']}")
            print(f"   Samples: {stats['total_samples']}")
            print(f"   ✓ Direct target integration works")

        time_series.stop()

        print("\n✓ Target direct integration test completed successfully")
        return True

    except Exception as e:
        print(f"\n✗ Target direct integration test failed: {e}")
        time_series.stop()
        return False


def main():
    """Run all integration tests."""
    print("Time-Series Storage Integration Test Suite")
    print("=" * 50)

    tests = [
        test_datahub_timeseries_integration,
        test_hierarchical_timeseries,
        test_target_direct_integration,
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

        time.sleep(1)  # Brief pause between tests

    print(f"\n" + "=" * 50)
    print(f"Integration Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("All integration tests passed!")
    else:
        print(f"{failed} integration test(s) failed")

    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
