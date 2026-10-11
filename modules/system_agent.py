import datetime
import json
import platform
import time

import psutil


def _up_time_text(seconds):
    minutes = int(seconds) // 60
    parts = []
    for count, word in ((minutes // 1440, "day"), (minutes % 1440 // 60, "hour"), (minutes % 60, "minute")):
        if count:
            parts.append(f"{count} {word}{'' if count == 1 else 's'}")
    return ", ".join(parts) or "0 minutes"


class SystemMetricsMixin:

    def init_system_metrics(self):
        device_cfg = self.config.get("device", {}) or {}
        metrics_cfg = self.config.get("metrics", {}) or {}
        self._metrics_enabled = bool(metrics_cfg.get("enabled", True))
        self._metrics_interval = float(metrics_cfg.get("update_interval", 15))
        self._agent_icon = device_cfg.get("agent_icon") or "mdi:microsoft-windows"
        host_cfg = metrics_cfg.get("host_cpu_load") or {}
        self._host_cpu_enabled = bool(host_cfg.get("enabled", False))
        self._host_cpu_name = host_cfg.get("name") or "Host CPU Load"
        agent_name = str(device_cfg.get("name") or "")
        if agent_name and not self._host_cpu_name.lower().startswith(agent_name.lower() + " "):
            self._host_cpu_name = f"{agent_name} {self._host_cpu_name}"
        try:
            self._host_cpu_cores = max(1, int(host_cfg.get("host_cores", 1)))
        except (TypeError, ValueError):
            self._host_cpu_cores = 1
        self._vm_cpu_cores = psutil.cpu_count(logical=True) or 1
        try:
            self._kernel_version = platform.version() or "unknown"
        except Exception:
            self._kernel_version = "unknown"
        self._startup_time = datetime.datetime.now().strftime("%H:%M:%S %d.%m.%y")
        psutil.cpu_percent(interval=None)

    def register_system_metrics(self):
        self._sensor_discovery(
            "agent_icon",
            "Agent icon",
            f"{self.base_topic}/agent_icon",
            icon="mdi:image-marker-outline",
            entity_category="diagnostic",
        )
        self.publish(f"{self.base_topic}/agent_icon", self._agent_icon, retain=True)

        self._sensor_discovery(
            "startup_time",
            "Startup time",
            f"{self.base_topic}/startup_time",
            icon="mdi:clock-start",
            entity_category="diagnostic",
        )
        self.publish(f"{self.base_topic}/startup_time", self._startup_time, retain=True)

        if not self._metrics_enabled:
            return

        self._sensor_discovery(
            "cpu_load",
            "CPU load",
            f"{self.base_topic}/cpu_load",
            unit="%",
            icon="mdi:cpu-64-bit",
            state_class="measurement",
        )
        if self._host_cpu_enabled:
            attrs_topic = f"{self.base_topic}/host_cpu_load_attrs"
            self._sensor_discovery(
                "host_cpu_load",
                self._host_cpu_name,
                f"{self.base_topic}/host_cpu_load",
                unit="%",
                icon="mdi:cpu-64-bit",
                state_class="measurement",
                attributes_topic=attrs_topic,
            )
            self.publish(attrs_topic, json.dumps({"hostname": self.config["device"]["name"]}))
        self._sensor_discovery(
            "memory_used_percent",
            "Memory used percent",
            f"{self.base_topic}/memory_used_percent",
            unit="%",
            icon="mdi:memory",
            ha_object_id=f"{self.device_slug}_memory_used",
            state_class="measurement",
        )

        self._sensor_discovery(
            "status_processes",
            "Processes",
            f"{self.base_topic}/processes",
            icon="mdi:format-list-numbered",
        )
        self._sensor_discovery(
            "status_kernel_version",
            "Kernel Version",
            f"{self.base_topic}/kernel_version",
            icon="mdi:microsoft-windows",
        )
        self._sensor_discovery(
            "status_up_time",
            "Up Time",
            f"{self.base_topic}/up_time",
            icon="mdi:timer-outline",
        )
        self.publish(f"{self.base_topic}/kernel_version", self._kernel_version, retain=True)
        self._publish_host_status()

    def _publish_host_status(self):
        self._host_status_published = time.time()
        self.publish(f"{self.base_topic}/processes", len(psutil.pids()))
        self.publish(f"{self.base_topic}/up_time", _up_time_text(time.time() - psutil.boot_time()))

    def system_metrics_loop(self):
        if not self._metrics_enabled:
            return
        while not self._stop_event.is_set():
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                self.publish(f"{self.base_topic}/cpu_load", round(cpu, 1))
                self.publish(f"{self.base_topic}/memory_used_percent", round(mem, 1))
                if self._host_cpu_enabled:
                    host_load = max(0.0, min(100.0, cpu * self._vm_cpu_cores / self._host_cpu_cores))
                    self.publish(f"{self.base_topic}/host_cpu_load", round(host_load, 2))
                if time.time() - getattr(self, "_host_status_published", 0) >= 60:
                    self._publish_host_status()
            except Exception as e:
                print(f"TuxD-Win: system_metrics_loop error: {e!r}")
            self._stop_event.wait(timeout=self._metrics_interval)
