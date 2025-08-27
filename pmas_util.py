import logging
import os
from threading import Lock
from enum import Enum, auto
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler

import asyncio  # for queue broker
from typing import Dict, Optional



job_id_var = ContextVar("job_id", default="-")

class JobIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = job_id_var.get()
        return True
    
    
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

                logger = logging.getLogger('pianif_logger')
                logger.setLevel(conf.log_setup_level)

                if logger.hasHandlers():
                    logger.handlers.clear()

                # File handler
                #   remove previous file:
                #if os.path.exists(log_file):
                #    os.remove(log_file)
                #file_handler = logging.FileHandler(log_file, encoding='utf-8')
                
                # Rotate, don't delete
                file_handler = RotatingFileHandler(
                    conf.log_file_path, mode="a", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
                )
                file_handler.setLevel(conf.log_file_level)

                # Console handler
                console_handler = logging.StreamHandler()
                console_handler.setLevel(conf.log_console_level)

                formatter = logging.Formatter("%(levelname)s [%(job_id)s] %(message)s")
                #formatter = logging.Formatter("%(asctime)s %(levelname)s [%(job_id)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
                #formatter = logging.Formatter('%(message)s')
                
                file_handler.setFormatter(formatter)
                console_handler.setFormatter(formatter)

                logger.addHandler(file_handler)
                logger.addHandler(console_handler)

                # inject job_id into every record
                logger.addFilter(JobIdFilter())
                
                PmasLoggerSingleton._instance = logger

            return PmasLoggerSingleton._instance




# Log Broker communicate server --> browser
#    logs of the running simulation
class PmasLogBroker:
    """
    Per-job log broker.
    - Coroutines can `await put(...)`.
    - Threads can `put_threadsafe(...)` (scheduled onto the event loop).
    - Use `done(...)` / `done_threadsafe(...)` to send the completion sentinel.
    """
    def __init__(self, maxsize: int = 1000, logger: Optional[logging.Logger] = None):
        self._qs: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._maxsize = maxsize
        # you can still use your singleton; falling back to std logging
        try:
            from pmas_util import PmasLoggerSingleton  # if available
            self._log = logger or PmasLoggerSingleton.get_logger()
        except Exception:
            self._log = logger or logging.getLogger("pmas.logbroker")
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # bound event loop

    # Call once on startup (from an async context) or pass loop in __init__ if you prefer
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        self._log.debug("broker: put line (await) job=%s: %s", job_id, line)
        await q.put(line)

    def _schedule(self, coro: asyncio.coroutines) -> None:
        """
        Schedule a coroutine safely on the bound loop from any thread.
        """
        if not self._loop:
            # best-effort fallback: try current running loop (may fail in threads)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._log.warning("broker: no event loop bound; dropping message")
                return
        else:
            loop = self._loop
        loop.call_soon_threadsafe(asyncio.create_task, coro)

    def put_threadsafe(self, job_id: str, line: str) -> None:
        q = self._qs.get(job_id)
        if not q or not (self._loop or asyncio.get_event_loop):
            return
        # Schedule an awaited put on the loop (no QueueFull exceptions)
        self._log.debug("broker: put line (threadsafe) job=%s: %s", job_id, line)
        self._schedule(q.put(line))

    async def done(self, job_id: str) -> None:
        q = self._qs.get(job_id)
        if q is not None:
            self._log.debug("broker: marking job %s as done (await)", job_id)
            await q.put("__DONE__")

    def done_threadsafe(self, job_id: str) -> None:
        q = self._qs.get(job_id)
        if not q:
            return
        self._log.debug("broker: marking job %s as done (threadsafe)", job_id)
        self._schedule(q.put("__DONE__"))

    def pop(self, job_id: str) -> None:
        self._qs.pop(job_id, None)


