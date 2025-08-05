import logging
import os
from threading import Lock
from enum import Enum, auto


class PhaseType(Enum):
    ENGINEERING = auto()
    PRODUCTION = auto()


def format_time(dt): return dt.strftime("%Y-%m-%d %H:%M")
def format_date(dt): return dt.strftime("%Y-%m-%d")
def format_time_only(dt): return dt.strftime("%H:%M")


class PmasLoggerSingleton:
    _instance = None
    _lock = Lock()

    # warning: with logger use a lazy string formatting like
    # glog.debug("%s - %s", self.current_time.strftime('%Y-%m-%d %H:%M'), message)
    # instead of
    # glog.debug(f"")

    @staticmethod
    def get_logger(conf=None):
        with PmasLoggerSingleton._lock:
            if PmasLoggerSingleton._instance is None:
                if conf is None:
                    raise ValueError("Logger must be initialized with a configuration on first call")

                log_file = conf.log_file_path
                if os.path.exists(log_file):
                    os.remove(log_file)

                logger = logging.getLogger('pianif_logger')
                logger.setLevel(conf.log_setup_level)

                if logger.hasHandlers():
                    logger.handlers.clear()

                # File handler
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_handler.setLevel(conf.log_file_level)

                # Console handler
                console_handler = logging.StreamHandler()
                console_handler.setLevel(conf.log_console_level)

                formatter = logging.Formatter('%(message)s')
                file_handler.setFormatter(formatter)
                console_handler.setFormatter(formatter)

                logger.addHandler(file_handler)
                logger.addHandler(console_handler)

                PmasLoggerSingleton._instance = logger

            return PmasLoggerSingleton._instance

