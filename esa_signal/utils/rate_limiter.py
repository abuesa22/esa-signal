import time
import threading
from collections import defaultdict, deque
from config import RATE_LIMITS


class RateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self):
        self._lock = threading.Lock()
        self._calls: dict[str, deque] = defaultdict(deque)

    def wait(self, api_name: str):
        cfg = RATE_LIMITS.get(api_name)
        if not cfg:
            return
        max_calls = cfg["calls"]
        period = cfg["period"]

        with self._lock:
            calls = self._calls[api_name]
            now = time.monotonic()

            # Drop calls outside the sliding window
            while calls and calls[0] < now - period:
                calls.popleft()

            if len(calls) >= max_calls:
                sleep_for = period - (now - calls[0]) + 0.05
                time.sleep(max(0.0, sleep_for))
                # Re-prune after sleeping
                now = time.monotonic()
                while calls and calls[0] < now - period:
                    calls.popleft()

            calls.append(time.monotonic())


# Singleton used across the whole application
rate_limiter = RateLimiter()
