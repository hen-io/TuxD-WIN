import json
import threading
from contextlib import contextmanager


class ProblemsMixin:

    def init_problems(self):
        self._problems = {"warning": {}, "error": {}}

    def register_problems(self):
        for level, name, icon in (("error", "Error", "mdi:alert-circle"), ("warning", "Warning", "mdi:alert")):
            self._binary_sensor_discovery(
                f"system_{level}", name, f"{self.base_topic}/{level}",
                device_class="problem" if level == "error" else None, icon=icon,
                attributes_topic=f"{self.base_topic}/{level}_attributes", entity_category="diagnostic",
            )
            self._sensor_discovery(
                f"system_{level}_reason", f"{name} Reason", f"{self.base_topic}/{level}_reason",
                icon=f"{icon}-outline", entity_category="diagnostic",
            )
            self._publish_problem(level)

    def set_standing(self, level, key, reason):
        current = self._problems[level]
        if current.get(key, "") == (reason or ""):
            return
        if reason:
            current[key] = reason
        else:
            current.pop(key, None)
        self._publish_problem(level)

    def _publish_problem(self, level):
        sources = dict(self._problems[level])
        reason = "; ".join(sources.values())
        self.publish(f"{self.base_topic}/{level}", "ON" if sources else "OFF")
        self.publish(f"{self.base_topic}/{level}_attributes", json.dumps({"reason": reason, "sources": sources}))
        self.publish(f"{self.base_topic}/{level}_reason", reason)


class BusyMixin:

    def init_busy(self):
        self._busy_lock = threading.Lock()
        self._busy_jobs = []

    def register_busy(self):
        self._binary_sensor_discovery(
            "system_busy",
            "Busy",
            f"{self.base_topic}/busy",
            icon="mdi:progress-clock",
            entity_category="diagnostic",
        )
        self._sensor_discovery(
            "system_busy_job",
            "Current Job",
            f"{self.base_topic}/busy_job",
            icon="mdi:format-list-bulleted",
            entity_category="diagnostic",
        )
        self._publish_busy()

    def _publish_busy(self):
        jobs = list(self._busy_jobs)
        if not jobs:
            text = ""
        elif len(jobs) == 1:
            text = jobs[-1]
        else:
            text = f"{jobs[-1]} (+{len(jobs) - 1} more)"
        self.publish(f"{self.base_topic}/busy", "ON" if jobs else "OFF")
        self.publish(f"{self.base_topic}/busy_job", text)

    @contextmanager
    def busy(self, description=""):
        job = description or "task"
        with self._busy_lock:
            self._busy_jobs.append(job)
            self._publish_busy()
        try:
            yield
        finally:
            with self._busy_lock:
                try:
                    self._busy_jobs.remove(job)
                except ValueError:
                    pass
                self._publish_busy()
