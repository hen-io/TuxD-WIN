import datetime

import psutil


class SystemMetricsMixin:

    def init_system_metrics(self):
        device_cfg = self.config.get("device", {}) or {}
        metrics_cfg = self.config.get("metrics", {}) or {}
        self._metrics_enabled = bool(metrics_cfg.get("enabled", True))
        self._metrics_interval = float(metrics_cfg.get("update_interval", 15))
        self._agent_icon = device_cfg.get("agent_icon") or "mdi:microsoft-windows"
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
        self._sensor_discovery(
            "memory_used_percent",
            "Memory used percent",
            f"{self.base_topic}/memory_used_percent",
            unit="%",
            icon="mdi:memory",
            ha_object_id=f"{self.device_slug}_memory_used",
            state_class="measurement",
        )

    def system_metrics_loop(self):
        if not self._metrics_enabled:
            return
        while not self._stop_event.is_set():
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                self.publish(f"{self.base_topic}/cpu_load", round(cpu, 1))
                self.publish(f"{self.base_topic}/memory_used_percent", round(mem, 1))
            except Exception as e:
                print(f"TuxD-Win: system_metrics_loop error: {e!r}")
            self._stop_event.wait(timeout=self._metrics_interval)
