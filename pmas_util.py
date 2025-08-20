import logging
import os
from threading import Lock
from enum import Enum, auto

import asyncio  # for queue broker
from typing import Dict, Optional



class PhaseType(Enum):
    ENGINEERING = auto()
    PRODUCTION = auto()


def format_time(dt): return dt.strftime("%Y-%m-%d %H:%M")
def format_date(dt): return dt.strftime("%Y-%m-%d")
def format_time_only(dt): return dt.strftime("%H:%M")


    
# logger to file / console as a singleton
class PmasLoggerSingleton:
    _instance = None
    _lock = Lock()

    # warning: with logger we should use a lazy string formatting like
    # glog.debug("%s - %s", self.current_time.strftime('%Y-%m-%d %H:%M'), message)
    # instead of
    # glog.debug(f"{message}")

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




# Log Broker for communication server --> browser
# of the log of the running simulation
class PmasLogBroker:
    glog: PmasLoggerSingleton = None
    
    def __init__(self, maxsize: int = 1000):
        self._qs: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        self.glog = PmasLoggerSingleton.get_logger()

    async def ensure(self, job_id: str) -> asyncio.Queue:
        async with self._lock:
            q = self._qs.get(job_id)
            if q is None:
                q = asyncio.Queue(maxsize=self._maxsize)
                self._qs[job_id] = q
            return q

    def get(self, job_id: str) -> Optional[asyncio.Queue]:
        return self._qs.get(job_id)
    #####
    # note:  This annotation:
    #    def get(self, job_id: str) -> asyncio.Queue[str] | None:
    #
    # uses the 3.10 “pipe” unions (|) and PEP-585 generics (like dict[str, …]). 
    # On 3.8/3.9 that raises:
    #    TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' 
    #####

    async def put(self, job_id: str, line: str) -> None:
        q = await self.ensure(job_id)
        self.glog.debug("broker: put line in queue for job %s: %s", job_id, line)
        await q.put(line)

    async def done(self, job_id: str) -> None:
        q = self._qs.get(job_id)
        if q is not None:
            self.glog.debug("broker: marking job %s as done", job_id)
            await q.put("__DONE__")

    def pop(self, job_id: str) -> None:
        self._qs.pop(job_id, None)

