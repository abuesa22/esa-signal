"""
Watchdog — keeps main.py running forever.
If the bot crashes or exits for any reason, waits 15 seconds and restarts it.
Logs every restart to watchdog.log.
"""
import subprocess
import sys
import time
import logging
from pathlib import Path

LOG_FILE = Path(__file__).parent / "watchdog.log"
PYTHON = sys.executable
BOT = Path(__file__).parent / "main.py"
WORKDIR = Path(__file__).parent

_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if sys.stderr is not None:
    _handlers.append(logging.StreamHandler())
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("watchdog")

RESTART_DELAY = 15   # seconds to wait before restarting after a crash
MAX_FAST_EXITS = 5    # if bot exits this many times within FAST_EXIT_WINDOW
FAST_EXIT_WINDOW = 120  # seconds, treat as a boot-loop and slow down


def main():
    log.info("Watchdog started — monitoring %s", BOT)
    run_count = 0
    exit_times = []

    while True:
        run_count += 1
        started_at = time.time()
        log.info("Starting bot (run #%d)...", run_count)

        try:
            proc = subprocess.run(
                [PYTHON, str(BOT)],
                cwd=str(WORKDIR),
            )
            exit_code = proc.returncode
        except Exception as exc:
            log.error("Failed to launch bot: %s", exc)
            exit_code = -1

        elapsed = time.time() - started_at
        log.warning(
            "Bot exited — code=%s uptime=%.0fs run=#%d",
            exit_code, elapsed, run_count,
        )

        # Detect rapid boot-loop (crashed too fast too many times)
        now = time.time()
        exit_times = [t for t in exit_times if now - t < FAST_EXIT_WINDOW]
        exit_times.append(now)

        if len(exit_times) >= MAX_FAST_EXITS:
            delay = 120  # back off hard if crashing in a tight loop
            log.error(
                "Boot-loop detected (%d exits in %ds) — backing off %ds",
                len(exit_times), FAST_EXIT_WINDOW, delay,
            )
        else:
            delay = RESTART_DELAY

        log.info("Restarting in %ds...", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()
