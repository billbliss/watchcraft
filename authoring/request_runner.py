"""Foreground request planner. Never accepts or processes project executions."""
from __future__ import annotations

import argparse
import concurrent.futures
import threading
import uuid

from request_planning import prepare_request


def run_request_planner(args, q, *, stop=None, prepare=prepare_request):
    if not 1 <= args.max_videos <= 5000 or not 1 <= args.timeout_seconds <= 900:
        raise ValueError("Use a video limit from 1 to 5000 and a job timeout from 1 to 900 seconds")
    if not 2 <= args.poll_seconds <= 30:
        raise ValueError("Poll interval must be between 2 and 30 seconds")
    stop = stop or threading.Event()
    control = q.operator_client(args.operator_token_source)
    runner_id = str(uuid.uuid4())
    # Resolve connectivity before starting any preparation. Only one live
    # consumer may own this deployment's queue at a time.
    poll = lambda: control.post("/requests/poll", {"runner_id": runner_id})
    pending = poll()
    failures = 0
    print("Request planner connected. Waiting for requests marked for planning.", flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            while not stop.is_set():
                requests = pending["requests"]
                if requests:
                    selected = argparse.Namespace(**vars(args))
                    selected.request_id = requests[0]["request_id"]
                    selected.expected_revision = requests[0]["expected_revision"]
                    future = executor.submit(prepare, selected, q)
                    while True:
                        try:
                            future.result(timeout=args.poll_seconds)
                            break
                        except concurrent.futures.TimeoutError:
                            if future.done():
                                raise  # A TimeoutError from preparation itself.
                            poll()  # Keep the connection live while preparing.
                        except Exception as error:
                            failures += 1
                            print(f"Preparation error: {error}", flush=True)
                            print("Request preparation stopped. Check its status in the portal and retry after resolving the cause.", flush=True)
                            break
                    if args.once:
                        break
                elif args.once:
                    break
                if stop.wait(args.poll_seconds):
                    break
                pending = poll()
    finally:
        try:
            control.post("/requests/disconnect", {"runner_id": runner_id})
        except Exception:
            pass  # The heartbeat expires if the connection is unavailable.
    return 1 if failures else 0
