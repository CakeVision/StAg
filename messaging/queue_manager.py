#!/usr/bin/env python3
"""
Test script for the new queue-based component architecture.
Tests the clean API and component interactions.
"""

import socket
import time
from pathlib import Path

from components.base import ManagedComponent, connect_components, create_pipeline

from config.targets import get_quick_test_config
from config.time_series import AggregationMethod, TimeSeriesConfig
from logger.json_logger import setup_application_logging
from messaging.queue_manager import cleanup_queue_managers, get_queue_manager
from monitors.base import BaseMetrics
from monitors.systems import SystemMonitor


class TestDataProducer(ManagedComponent):
    """Simple test component that produces data."""

    def __init__(self, name: str, logger_manager=None):
        super().__init__(name, logger_manager=logger_manager)
        self.data_count = 0
        self._producer_thread = None
        self._shutdown_event = None

    def start(self):
        super().start()

        import threading

        self._shutdown_event = threading.Event()
        self._producer_thread = threading.Thread(target=self._produce_loop, daemon=True)
        self._producer_thread.start()

        if self.logger:
            self.logger.log_system_event(
                "producer_start", f"Producer {self.name} started"
            )

    def stop(self, timeout=5.0):
        if self._shutdown_event:
            self._shutdown_event.set()

        if self._producer_thread:
            self._producer_thread.join(timeout=timeout)

        super().stop(timeout)

    def _produce_loop(self):
        """Produce test data every 2 seconds."""
        while not self._shutdown_event.wait(timeout=2.0):
            data = {
                "source": self.name,
                "timestamp": time.time(),
                "data_count": self.data_count,
                "test_value": 10 + self.data_count * 5,
            }

            success = self._publish_data(data)
            if success:
                self.data_count += 1
                if self.logger:
                    self.logger.log_system_event(
                        "data_produced",
                        f"Produced data item {self.data_count}",
                        data_count=self.data_count,
                    )


class TestDataConsumer(ManagedComponent):
    """Simple test component that consumes data."""

    def __init__(self, name: str, logger_manager=None):
        super().__init__(name, logger_manager=logger_manager)
        self.received_count = 0
        self.received_data = []
        self._consumer_thread = None
        self._shutdown_event = None

    def start(self):
        super().start()

        import threading

        self._shutdown_event = threading.Event()
        self._consumer_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._consumer_thread.start()

        if self.logger:
            self.logger.log_system_event(
                "consumer_start", f"Consumer {self.name} started"
            )

    def stop(self, timeout=5.0):
        if self._shutdown_event:
            self._shutdown_event.set()

        if self._consumer_thread:
            self._consumer_thread.join(timeout=timeout)

        super().stop(timeout)

    def _consume_loop(self):
        """Consume data from input queues."""
        while not self._shutdown_event.wait(timeout=0.5):
            try:
                data_items = self._consume_data(timeout=0.1)

                for data in data_items:
                    self.received_count += 1
                    self.received_data.append(data)

                    if self.logger:
                        self.logger.log_system_event(
                            "data_consumed",
                            f"Consumed data from {data.get('source', 'unknown')}",
                            received_count=self.received_count,
                            source=data.get("source"),
                        )

                    # Also republish (for chaining)
                    self._publish_data(
                        {
                            "processed_by": self.name,
                            "original_data": data,
                            "processed_at": time.time(),
                        }
                    )

            except Exception as e:
                if self.logger:
                    self.logger.log_error("Error in consumer loop", e)


class TestSystemProducer(ManagedComponent):
    """Test component that produces real system metrics."""

    def __init__(self, name: str, logger_manager=None):
        super().__init__(name, logger_manager=logger_manager)
        self.monitor = SystemMonitor(name)
        self.metrics_count = 0
        self._producer_thread = None
        self._shutdown_event = None

    def start(self):
        super().start()

        import threading

        self._shutdown_event = threading.Event()
        self._producer_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        self._producer_thread.start()

    def stop(self, timeout=5.0):
        if self._shutdown_event:
            self._shutdown_event.set()

        if self._producer_thread:
            self._producer_thread.join(timeout=timeout)

        super().stop(timeout)

    def _metrics_loop(self):
        """Collect and publish real system metrics."""
        while not self._shutdown_event.wait(timeout=3.0):
            try:
                metrics = self.monitor.collect_metrics()

                data = {
                    "target_name": self.name,
                    "target_type": "system",
                    "timestamp": time.time(),
                    "metrics": metrics.to_dict()
                    if isinstance(metrics, BaseMetrics)
                    else metrics,
                }

                success = self._publish_data(data)
                if success:
                    self.metrics_count += 1

            except Exception as e:
                if self.logger:
                    self.logger.log_error("Error collecting metrics", e)


def test_basic_queue_connection():
    """Test basic producer-consumer connection."""
    print("=== Testing Basic Queue Connection ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    try:
        # Create components
        producer = TestDataProducer("test-producer", log_manager)
        consumer = TestDataConsumer("test-consumer", log_manager)

        # Connect them using clean API
        print("1. Connecting producer to consumer...")
        queue_id = producer.add_consumer(consumer)
        print(f"   Created queue: {queue_id[:8]}...")

        # Start components
        print("2. Starting components...")
        producer.start()
        consumer.start()

        # Let them run
        print("3. Running for 8 seconds...")
        time.sleep(8)

        # Check results
        print("4. Checking results...")
        print(f"   Producer sent: {producer.data_count} items")
        print(f"   Consumer received: {consumer.received_count} items")

        # Stop components
        print("5. Stopping components...")
        producer.stop()
        consumer.stop()

        # Verify data flow
        success = consumer.received_count > 0
        print(f"   ✓ Data flow test: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"   ✗ Basic connection test failed: {e}")
        return False


def test_pipeline_creation():
    """Test creating a linear pipeline."""
    print("\n=== Testing Pipeline Creation ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    try:
        # Create pipeline components
        producer = TestDataProducer("pipeline-producer", log_manager)
        processor1 = TestDataConsumer("pipeline-processor1", log_manager)
        processor2 = TestDataConsumer("pipeline-processor2", log_manager)

        # Create pipeline using utility function
        print("1. Creating pipeline: producer -> processor1 -> processor2...")
        create_pipeline(producer, processor1, processor2)

        # Start all components
        print("2. Starting pipeline...")
        producer.start()
        processor1.start()
        processor2.start()

        # Let pipeline run
        print("3. Running pipeline for 10 seconds...")
        time.sleep(10)

        # Check results
        print("4. Checking pipeline results...")
        print(f"   Producer sent: {producer.data_count} items")
        print(f"   Processor1 received: {processor1.received_count} items")
        print(f"   Processor2 received: {processor2.received_count} items")

        # Stop pipeline
        print("5. Stopping pipeline...")
        producer.stop()
        processor1.stop()
        processor2.stop()

        # Verify pipeline worked
        success = processor1.received_count > 0 and processor2.received_count > 0
        print(f"   ✓ Pipeline test: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"   ✗ Pipeline test failed: {e}")
        return False


def test_component_restart():
    """Test component restart with queue preservation."""
    print("\n=== Testing Component Restart ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    try:
        # Create components
        producer = TestDataProducer("restart-producer", log_manager)
        consumer = TestDataConsumer("restart-consumer", log_manager)

        # Connect them
        print("1. Setting up producer-consumer connection...")
        producer.add_consumer(consumer)

        # Start components
        producer.start()
        consumer.start()
        time.sleep(3)

        initial_received = consumer.received_count
        print(f"   Initial data received: {initial_received}")

        # Restart producer
        print("2. Restarting producer...")
        restart_success = producer.restart()
        print(f"   Producer restart: {'success' if restart_success else 'failed'}")

        # Let it run more
        print("3. Running after restart for 5 seconds...")
        time.sleep(5)

        final_received = consumer.received_count
        print(f"   Final data received: {final_received}")

        # Stop components
        producer.stop()
        consumer.stop()

        # Check restart worked
        success = final_received > initial_received and restart_success
        print(f"   ✓ Restart test: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"   ✗ Restart test failed: {e}")
        return False


def test_real_system_metrics():
    """Test with real system metrics collection."""
    print("\n=== Testing Real System Metrics ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    try:
        # Create real system monitor
        system_producer = TestSystemProducer("localhost", log_manager)
        metrics_consumer = TestDataConsumer("metrics-processor", log_manager)

        # Connect them
        print("1. Connecting system monitor to metrics processor...")
        system_producer.add_consumer(metrics_consumer)

        # Start components
        print("2. Starting system monitoring...")
        system_producer.start()
        metrics_consumer.start()

        # Let it collect real metrics
        print("3. Collecting real system metrics for 12 seconds...")
        time.sleep(12)

        # Check results
        print("4. Checking metrics collection...")
        print(f"   System metrics collected: {system_producer.metrics_count}")
        print(f"   Metrics processed: {metrics_consumer.received_count}")

        # Show sample data
        if metrics_consumer.received_data:
            sample = metrics_consumer.received_data[-1]
            metrics = sample.get("metrics", {})
            if "cpu" in metrics:
                cpu_percent = metrics["cpu"].get("percent", "N/A")
                print(f"   Sample CPU usage: {cpu_percent}%")

        # Stop components
        print("5. Stopping system monitoring...")
        system_producer.stop()
        metrics_consumer.stop()

        # Verify real metrics
        success = (
            system_producer.metrics_count > 0 and metrics_consumer.received_count > 0
        )
        print(f"   ✓ System metrics test: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"   ✗ System metrics test failed: {e}")
        return False


def test_queue_statistics():
    """Test queue manager statistics."""
    print("\n=== Testing Queue Statistics ===")

    log_manager = setup_application_logging(
        log_dir=Path("logs"), hostname=socket.gethostname(), use_colors=True
    )

    try:
        # Get queue manager
        queue_manager = get_queue_manager("main", log_manager)

        # Create components to generate queues
        producer = TestDataProducer("stats-producer", log_manager)
        consumer1 = TestDataConsumer("stats-consumer1", log_manager)
        consumer2 = TestDataConsumer("stats-consumer2", log_manager)

        print("1. Creating multi-consumer setup...")
        producer.add_consumer(consumer1)
        producer.add_consumer(consumer2)

        # Start and run briefly
        producer.start()
        consumer1.start()
        consumer2.start()
        time.sleep(5)

        # Get queue statistics
        print("2. Checking queue statistics...")
        queue_stats = queue_manager.list_queues()
        print(f"   Total queues: {len(queue_stats)}")

        for stats in queue_stats:
            print(
                f"   Queue {stats['name']}: {stats['messages_sent']} sent, {stats['size']} pending"
            )

        # Stop components
        producer.stop()
        consumer1.stop()
        consumer2.stop()

        success = len(queue_stats) > 0
        print(f"   ✓ Queue statistics test: {'PASS' if success else 'FAIL'}")

        return success

    except Exception as e:
        print(f"   ✗ Queue statistics test failed: {e}")
        return False


def main():
    """Run all queue architecture tests."""
    print("Queue-Based Component Architecture Test Suite")
    print("=" * 50)

    tests = [
        test_basic_queue_connection,
        test_pipeline_creation,
        test_component_restart,
        test_real_system_metrics,
        test_queue_statistics,
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

        # Brief pause between tests
        time.sleep(1)

    # Cleanup
    print("\nCleaning up queue managers...")
    cleanup_queue_managers()

    print(f"\n" + "=" * 50)
    print(f"Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("All architecture tests passed!")
        print("\nThe queue-based component architecture is working correctly:")
        print("- Clean API for connecting components")
        print("- Automatic queue creation and management")
        print("- Component restart with queue preservation")
        print("- Real system metrics collection")
        print("- Pipeline creation utilities")
        print("- Queue statistics and monitoring")
    else:
        print(f"{failed} architecture test(s) failed")

    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
