"""One thread for everything that runs on MLX (the voices and Whisper).

MLX must be used from a single thread, so web requests hand their work to this thread and wait.
"""

import queue
import threading


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
        while True:
            job = self.jobs.get()
            try:
                job["result"] = job["function"]()
            except Exception as error:  # hand it to the waiting caller, keep the thread alive
                job["error"] = error
            finally:
                job["done"].set()
