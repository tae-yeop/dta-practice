"""Runtime budgets and cleanup for the prediction process tree we own."""

import os
from contextlib import contextmanager
import signal
import subprocess
import time

from .models import MODEL, MODELS, PROJECT, ToolError


@contextmanager
def device_lock(device, timeout=3600):
    """Serialize this project's CUDA jobs across CLI, MCP and web processes.

    The OS releases the byte/file lock if a worker exits or is killed.
    """
    if device != "cuda":
        yield
        return
    path = PROJECT / "runs" / ".gpu.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ToolError("DEVICE_BUSY", "Another project prediction is using CUDA; retry when it completes.")
                time.sleep(.25)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def request_timeout(arguments):
    if not isinstance(arguments, dict):
        return 180
    names = arguments.get("models", [arguments.get("model", MODEL)])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        return 180
    return max(180, sum(MODELS.get(name, {}).get("timeout_seconds", 0) for name in set(names)) + 60)


def process_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def terminate_process_tree(process):
    """Terminate only the subprocess tree created by this request."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=30, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=30)
