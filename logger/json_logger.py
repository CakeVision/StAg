"""
JSON logging framework with rotation for homelab monitoring.

Provides structured logging with daily rotation, metadata enrichment,
field exclusion, section context management, and ANSI colors.
"""

import json
import logging
import logging.handlers
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set, Union


@dataclass
class LogContext:
    """Context information for log entries."""

    host: str
    component: str
    target: Optional[str] = None
    target_type: Optional[str] = None


class ANSIColors:
    """ANSI color codes for console output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Standard colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def colorize(cls, text: str, color: str, bold: bool = False) -> str:
        """Colorize text with ANSI codes."""
        prefix = f"{cls.BOLD if bold else ''}{color}"
        return f"{prefix}{text}{cls.RESET}"

    @classmethod
    def level_color(cls, level: str) -> str:
        """Get color for log level."""
        colors = {
            "DEBUG": cls.BRIGHT_BLACK,
            "INFO": cls.BRIGHT_BLUE,
            "WARNING": cls.BRIGHT_YELLOW,
            "ERROR": cls.BRIGHT_RED,
            "CRITICAL": cls.BG_RED + cls.BRIGHT_WHITE,
        }
        return colors.get(level.upper(), cls.WHITE)


def exclude_fields(data: Dict[str, Any], exclude: Set[str]) -> Dict[str, Any]:
    """Recursively exclude fields from dictionary."""
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if key in exclude:
            result[key] = "<excluded>"
        elif isinstance(value, dict):
            result[key] = exclude_fields(value, exclude)
        elif isinstance(value, list):
            result[key] = [
                exclude_fields(item, exclude) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


class JSONFormatter(logging.Formatter):
    """Custom formatter for structured JSON logs."""

    def __init__(
        self,
        context: Optional[LogContext] = None,
        exclude_fields: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.context = context
        self.exclude_fields = exclude_fields or set()

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with metadata."""
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context if available
        if self.context:
            log_entry["context"] = asdict(self.context)

        # Add extra fields from log record
        if hasattr(record, "extra_fields"):
            extra_fields = record.extra_fields
            if self.exclude_fields:
                extra_fields = exclude_fields(extra_fields, self.exclude_fields)
            log_entry.update(extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """Console formatter with ANSI colors and readable format."""

    def __init__(
        self,
        context: Optional[LogContext] = None,
        exclude_fields: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.context = context
        self.exclude_fields = exclude_fields or set()
        self.use_color = sys.stderr.isatty()  # Only use colors if stderr is a terminal

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors and readable layout."""
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = record.levelname

        if self.use_color:
            level_colored = ANSIColors.colorize(
                f"{level:8s}", ANSIColors.level_color(level), bold=True
            )
            timestamp_colored = ANSIColors.colorize(timestamp, ANSIColors.BRIGHT_BLACK)
            module_colored = ANSIColors.colorize(
                f"{record.module}:{record.lineno}", ANSIColors.CYAN
            )
        else:
            level_colored = f"{level:8s}"
            timestamp_colored = timestamp
            module_colored = f"{record.module}:{record.lineno}"

        base_msg = f"{timestamp_colored} {level_colored} {module_colored} {record.getMessage()}"

        # Add context and extra fields
        extras = []
        if self.context:
            if self.context.target:
                extras.append(f"target={self.context.target}")
            if self.context.component != "main":
                extras.append(f"component={self.context.component}")

        if hasattr(record, "extra_fields"):
            extra_fields = record.extra_fields
            if self.exclude_fields:
                extra_fields = exclude_fields(extra_fields, self.exclude_fields)

            for key, value in extra_fields.items():
                if key not in ["event_type"]:  # Skip some noise
                    if isinstance(value, (int, float)):
                        extras.append(f"{key}={value}")
                    else:
                        extras.append(
                            f"{key}={str(value)[:50]}"
                        )  # Truncate long values

        if extras:
            extra_str = " ".join(extras)
            if self.use_color:
                extra_str = ANSIColors.colorize(f"[{extra_str}]", ANSIColors.DIM)
            else:
                extra_str = f"[{extra_str}]"
            base_msg += f" {extra_str}"

        # Add exception info if present
        if record.exc_info:
            base_msg += f"\n{self.formatException(record.exc_info)}"

        return base_msg


class RotatingJSONLogger:
    """JSON logger with daily rotation, field exclusion, sections, and colors."""

    def __init__(
        self,
        name: str,
        log_dir: Path,
        context: Optional[LogContext] = None,
        level: int = logging.INFO,
        max_files: int = 10,
        backup_count: int = 10,
        exclude_fields: Optional[Set[str]] = None,
        use_colors: bool = True,
    ):
        self.name = name
        self.log_dir = Path(log_dir)
        self.context = context
        self.max_files = max_files
        self.exclude_fields = exclude_fields or set()
        self.use_colors = use_colors
        self._section_stack = []  # For nested sections

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Prevent duplicate handlers
        if not self.logger.handlers:
            self._setup_handlers()

    def _setup_handlers(self):
        """Set up file and console handlers."""
        # File handler with daily rotation
        log_file = self.log_dir / f"{self.name}.log"
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=self.max_files,
            encoding="utf-8",
        )
        file_handler.setFormatter(JSONFormatter(self.context, self.exclude_fields))

        # Console handler with colors
        console_handler = logging.StreamHandler()
        if self.use_colors:
            console_handler.setFormatter(
                ColoredConsoleFormatter(self.context, self.exclude_fields)
            )
        else:
            console_handler.setFormatter(
                JSONFormatter(self.context, self.exclude_fields)
            )

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    @contextmanager
    def section(self, section_name: str, level: int = logging.INFO, **kwargs):
        """Context manager for logging sections with enter/exit events."""
        section_id = f"{section_name}_{len(self._section_stack)}"
        self._section_stack.append(section_id)

        # Log section start
        start_fields = {
            "event_type": "section_start",
            "section_name": section_name,
            "section_id": section_id,
            "section_depth": len(self._section_stack),
            **kwargs,
        }

        start_time = datetime.now()
        self.logger.log(
            level,
            f"→ Starting section: {section_name}",
            extra={"extra_fields": start_fields},
        )

        try:
            yield self
        except Exception as e:
            # Log section error
            error_fields = {
                "event_type": "section_error",
                "section_name": section_name,
                "section_id": section_id,
                "error_type": type(e).__name__,
                "error": str(e),
            }
            self.logger.error(
                f"✗ Section failed: {section_name}",
                exc_info=e,
                extra={"extra_fields": error_fields},
            )
            raise
        finally:
            # Log section end
            end_time = datetime.now()
            duration_ms = (end_time - start_time).total_seconds() * 1000

            end_fields = {
                "event_type": "section_end",
                "section_name": section_name,
                "section_id": section_id,
                "duration_ms": round(duration_ms, 2),
                "section_depth": len(self._section_stack),
            }

            self.logger.log(
                level,
                f"← Completed section: {section_name} ({duration_ms:.1f}ms)",
                extra={"extra_fields": end_fields},
            )

            self._section_stack.pop()

    def exclude_sensitive_fields(self, *field_names: str):
        """Add fields to exclusion list."""
        self.exclude_fields.update(field_names)

    def log_metric_collection(
        self,
        target: str,
        target_type: str,
        metrics: Dict[str, Any],
        duration_ms: float,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """Log a metric collection event with structured data."""
        # Apply field exclusion to metrics
        safe_metrics = exclude_fields(metrics, self.exclude_fields) if metrics else {}

        extra_fields = {
            "event_type": "metric_collection",
            "target": target,
            "target_type": target_type,
            "duration_ms": duration_ms,
            "success": success,
            "metric_count": len(metrics) if metrics else 0,
        }

        if error:
            extra_fields["error"] = error

        # Add current section context
        if self._section_stack:
            extra_fields["section_context"] = self._section_stack[-1]

        if success:
            message = (
                f"Collected {len(metrics)} metrics from {target} in {duration_ms:.1f}ms"
            )
            self.logger.info(message, extra={"extra_fields": extra_fields})
        else:
            message = f"Failed to collect metrics from {target}: {error}"
            self.logger.error(message, extra={"extra_fields": extra_fields})

    def log_system_event(
        self, event_type: str, message: str, level: int = logging.INFO, **kwargs
    ):
        """Log a system event with additional context."""
        extra_fields = {"event_type": event_type, **kwargs}

        # Apply field exclusion
        if self.exclude_fields:
            extra_fields = exclude_fields(extra_fields, self.exclude_fields)

        # Add current section context
        if self._section_stack:
            extra_fields["section_context"] = self._section_stack[-1]

        self.logger.log(level, message, extra={"extra_fields": extra_fields})

    def log_error(self, message: str, error: Exception, **kwargs):
        """Log an error with exception details."""
        extra_fields = {
            "event_type": "error",
            "error_type": type(error).__name__,
            **kwargs,
        }

        # Apply field exclusion
        if self.exclude_fields:
            extra_fields = exclude_fields(extra_fields, self.exclude_fields)

        # Add current section context
        if self._section_stack:
            extra_fields["section_context"] = self._section_stack[-1]

        self.logger.error(message, exc_info=error, extra={"extra_fields": extra_fields})


class LoggerManager:
    """Central manager for all application loggers."""

    def __init__(
        self,
        log_dir: Path,
        default_context: Optional[LogContext] = None,
        global_exclude_fields: Optional[Set[str]] = None,
        use_colors: bool = True,
    ):
        self.log_dir = Path(log_dir)
        self.default_context = default_context
        self.global_exclude_fields = global_exclude_fields or set()
        self.use_colors = use_colors
        self.loggers: Dict[str, RotatingJSONLogger] = {}

    def get_logger(
        self,
        name: str,
        context: Optional[LogContext] = None,
        level: int = logging.INFO,
        exclude_fields: Optional[Set[str]] = None,
    ) -> RotatingJSONLogger:
        """Get or create a logger with the given name."""
        if name not in self.loggers:
            effective_context = context or self.default_context
            combined_exclude = self.global_exclude_fields.union(exclude_fields or set())

            self.loggers[name] = RotatingJSONLogger(
                name=name,
                log_dir=self.log_dir,
                context=effective_context,
                level=level,
                exclude_fields=combined_exclude,
                use_colors=self.use_colors,
            )
        return self.loggers[name]

    def get_component_logger(
        self,
        component: str,
        level: int = logging.INFO,
        exclude_fields: Optional[Set[str]] = None,
    ) -> RotatingJSONLogger:
        """Get a logger for a specific component."""
        context = LogContext(
            host=self.default_context.host if self.default_context else "unknown",
            component=component,
        )
        return self.get_logger(f"homelab.{component}", context, level, exclude_fields)

    def get_target_logger(
        self,
        target: str,
        target_type: str,
        level: int = logging.INFO,
        exclude_fields: Optional[Set[str]] = None,
    ) -> RotatingJSONLogger:
        """Get a logger for a specific monitoring target."""
        context = LogContext(
            host=self.default_context.host if self.default_context else "unknown",
            component="collector",
            target=target,
            target_type=target_type,
        )
        return self.get_logger(
            f"homelab.targets.{target}", context, level, exclude_fields
        )

    def add_global_exclusions(self, *field_names: str):
        """Add fields to global exclusion list."""
        self.global_exclude_fields.update(field_names)
        # Update existing loggers
        for logger in self.loggers.values():
            logger.exclude_sensitive_fields(*field_names)


# Example usage and testing functions
def setup_application_logging(
    log_dir: Path,
    hostname: str,
    exclude_sensitive: bool = True,
    use_colors: bool = True,
) -> LoggerManager:
    """Set up logging for the entire application."""
    default_context = LogContext(host=hostname, component="main")

    # Common sensitive fields to exclude
    sensitive_fields = set()
    if exclude_sensitive:
        sensitive_fields = {
            "password",
            "token",
            "secret",
            "key",
            "auth",
            "credential",
            "private_key",
            "api_key",
        }

    return LoggerManager(
        log_dir,
        default_context,
        global_exclude_fields=sensitive_fields,
        use_colors=use_colors,
    )


if __name__ == "__main__":
    """Test the enhanced logging framework."""
    import socket
    import time

    # Setup with enhanced features
    log_dir = Path("logs")
    hostname = socket.gethostname()
    log_manager = setup_application_logging(log_dir, hostname, use_colors=True)

    # Test different logger types
    main_logger = log_manager.get_component_logger("main")
    collector_logger = log_manager.get_component_logger("collector")

    # Add some field exclusions
    collector_logger.exclude_sensitive_fields("password", "secret_token")

    # Test colored logging
    main_logger.log_system_event(
        "startup", "🚀 Application starting up", version="1.0.0"
    )

    # Test section context manager
    with main_logger.section("initialization", priority="high") as section_logger:
        section_logger.log_system_event("config", "Loading configuration...")
        time.sleep(0.1)  # Simulate work

        with section_logger.section("database_setup") as db_logger:
            db_logger.log_system_event("db", "Connecting to database...")
            time.sleep(0.05)

        section_logger.log_system_event("config", "Configuration loaded successfully")

    # Test field exclusion
    sensitive_data = {
        "cpu": 45.2,
        "memory": 78.5,
        "password": "secret123",
        "secret_token": "abc123def456",
        "normal_field": "visible",
    }

    collector_logger.log_metric_collection(
        target="vm-001",
        target_type="virtual_machine",
        metrics=sensitive_data,
        duration_ms=125.3,
        success=True,
    )

    # Test error with section context
    with main_logger.section("error_demonstration"):
        try:
            raise ValueError("Test error for colored logging")
        except Exception as e:
            main_logger.log_error("Demonstration error occurred", e, component="test")

    print(f" Enhanced logs written to: {log_dir.absolute()}")
    print("  Features demonstrated:")
    print("  • ANSI colored console output")
    print("  • Section context management with timing")
    print("  • Sensitive field exclusion")
    print("  • Nested sections with hierarchical logging")
    print("  • JSON file output with all metadata")
    print("\nCheck both console output and log files!")
