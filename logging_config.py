"""
Centralized logging configuration for beanJAMinBOT
"""
import logging
import sys


def setup_logging(log_level=logging.INFO, log_file=None):
    """
    Configure logging for the entire application.

    Args:
        log_level: Logging level (default: INFO)
        log_file: Optional file path for log output

    Returns:
        Root logger for beanJAMinBOT
    """
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s"
    )

    root_logger = logging.getLogger('beanJAMinBOT')
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name):
    """
    Get a logger for a specific module.

    Args:
        name: Module name (will be prefixed with 'beanJAMinBOT.')

    Returns:
        Logger instance
    """
    return logging.getLogger(f'beanJAMinBOT.{name}')
