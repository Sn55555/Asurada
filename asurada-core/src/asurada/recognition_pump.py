"""One recognizer owner with a one-result mailbox and independent spoken stop."""
import queue
import threading
from .recognition_runtime import listen_with_context
from .spoken_stop import SpokenStopRouter
from .task_runtime import TaskContext, TaskCancelled, TaskCapacityExceeded


class RecognitionPump:
    def __init__(self, recognizer, *, wake_phrases, on_stop, scope_probe):
        self.recognizer = recognizer
        self.scope_probe = scope_probe
        self.router = SpokenStopRouter(wake_phrases=wake_phrases, on_stop=on_stop)
        self._results = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._generation = 0
        self._context = None
        self._thread = threading.Thread(target=self._run, name='voice-recognition-pump', daemon=True)
        self.dropped = 0
        self.last_error = None

    def start(self):
        self._thread.start()
        return self

    def invalidate(self):
        with self._lock:
            self._generation += 1
            if self._context is not None:
                self._context.cancel()
            while True:
                try: self._results.get_nowait()
                except queue.Empty: break

    def _offer(self, generation, scope, value):
        with self._lock:
            if generation != self._generation or self._closed.is_set():
                return
            if self._results.full():
                try:
                    self._results.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass
            self._results.put_nowait((generation, scope, value))

    def _run(self):
        while not self._closed.is_set():
            scope = None
            with self._lock:
                generation = self._generation
                context = self._context = TaskContext.start('continuous-recognition', 60000)
            try:
                scope = self.scope_probe()
                result = listen_with_context(self.recognizer, context)
                context.remaining()
                if self.scope_probe() != scope:
                    continue
                if self.router.accept(result):
                    self.invalidate()
                else:
                    self._offer(generation, scope, result)
            except (TaskCancelled, TaskCapacityExceeded):
                pass
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
                self._offer(generation, scope, exc)
            self._closed.wait(.02)

    def next_result(self, context):
        while True:
            context.remaining()
            try: generation, scope, result = self._results.get(timeout=min(.02, context.remaining()))
            except queue.Empty: continue
            context.remaining()
            with self._lock:
                if generation != self._generation:
                    continue
            if isinstance(result, Exception):
                raise result
            if scope != self.scope_probe():
                continue
            return result

    def close(self):
        self._closed.set()
        self.invalidate()
        self._thread.join(1)
        return not self._thread.is_alive()
