"""One thread for everything that runs on MLX (the voices and Whisper).

MLX must be used from a single thread, so web requests hand their work to this thread and wait.
"""

import queue
import sys
import threading


CACHE_LIMIT = 200 * 1024 * 1024  # how much spare GPU memory MLX may keep between jobs


def trim_memory():
    """Give back GPU memory that the last job no longer needs (this Mac has 8 GB, shared by everything)."""
    try:
        import mlx.core as mx

        (getattr(mx, "clear_cache", None) or mx.metal.clear_cache)()
    except Exception:
        pass
    if "torch" in sys.modules:
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:
            pass


def limit_cache():
    try:
        import mlx.core as mx

        (getattr(mx, "set_cache_limit", None) or mx.metal.set_cache_limit)(CACHE_LIMIT)
    except Exception:
        pass


class Worker:
    def __init__(self):
        self.jobs = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def run(self, function, timeout=300):
        """Run `function()` on the worker thread and return its result (or raise its error)."""
        job = {"function": function, "done": threading.Event(), "result": None, "error": None}
        self.jobs.put(job)
        if not job["done"].wait(timeout):
            raise RuntimeError("took too long")
        if job["error"] is not None:
            raise job["error"]
        return job["result"]

    def _loop(self):
        limit_cache()
        while True:
            job = self.jobs.get()
            try:
                job["result"] = job["function"]()
            except Exception as error:  # hand it to the waiting caller, keep the thread alive
                job["error"] = error
            finally:
                trim_memory()
                job["done"].set()
