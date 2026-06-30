"""In-memory per-job trace bus for the agent execution trace (Tier 2:
"Agent execution trace — which agent did what"). Events are appended by the
worker thread running the graph and streamed to clients over SSE.

A list + append is enough: CPython list.append is atomic, the SSE reader only
reads len()/index, and jobs are short-lived. Swap for Redis pub/sub when the
service goes multi-process.
"""

import threading
import time
import uuid
from collections import OrderedDict
from typing import List, Optional

MAX_JOBS = 200  # cap retained jobs so a long-running service doesn't leak memory


class TraceBus:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.events: List[dict] = []
        self.done = False
        self.result: Optional[dict] = None
        self.error: Optional[str] = None

    def emit(self, agent: str, message: str, **data):
        self.events.append({
            "ts": round(time.time(), 3),
            "agent": agent,
            "message": message,
            **data,
        })

    def finish(self, result: dict = None, error: str = None):
        self.result = result
        self.error = error
        self.done = True


_buses: "OrderedDict[str, TraceBus]" = OrderedDict()
_lock = threading.Lock()


def create() -> TraceBus:
    job_id = uuid.uuid4().hex[:12]
    bus = TraceBus(job_id)
    with _lock:
        _buses[job_id] = bus
        while len(_buses) > MAX_JOBS:
            _buses.popitem(last=False)  # evict oldest
    return bus


def get(job_id: str) -> Optional[TraceBus]:
    return _buses.get(job_id)
