"""Start the whole Command Server on one machine: the API (with the scheduler) and N workers.

    uv run python serve.py                 # API on 0.0.0.0:8000 and 3 workers
    uv run python serve.py --workers 4 --port 8000

Ctrl-C stops everything.
"""

import argparse
import signal
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host,
                               "--port", str(args.port), "--log-level", "warning"])]
    procs += [subprocess.Popen([sys.executable, "-m", "worker.main"]) for _ in range(args.workers)]
    print(f"Iron Curtain running on http://{args.host}:{args.port} with {args.workers} workers. Ctrl-C to stop.")

    def shutdown(*_):
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    while True:
        for i, p in enumerate(procs):
            if p.poll() is not None and i > 0:
                # A crashed worker is restarted; its leased jobs are reclaimed by the others
                print(f"Worker exited with {p.returncode}, restarting")
                procs[i] = subprocess.Popen([sys.executable, "-m", "worker.main"])
        if procs[0].poll() is not None:
            print("API process exited, stopping")
            shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()
