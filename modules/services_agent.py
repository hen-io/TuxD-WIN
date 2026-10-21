import json

import psutil

from .shared import slugify


class ServicesMixin:

    def init_services(self):
        services_cfg = self.config.get("services", {}) or {}
        self._services_enabled = bool(services_cfg.get("enabled", True))
        self._services_interval = float(services_cfg.get("update_interval", 30))
        self._service_names = [str(n) for n in (services_cfg.get("names") or [])]
        alert = str(services_cfg.get("alert", "warning") or "off").strip().lower()
        self._services_alert = alert if alert in ("warning", "error") else "off"

    def register_services(self):
        if not self._services_enabled:
            return
        for name in self._service_names:
            slug = slugify(name)
            self._binary_sensor_discovery(
                f"service_{slug}_running",
                f"Service: {name}",
                f"{self.base_topic}/service_{slug}_running",
                device_class="running",
                icon="mdi:cog",
                attributes_topic=f"{self.base_topic}/service_{slug}_attrs",
            )

    def services_loop(self):
        if not self._services_enabled or not self._service_names:
            return
        while not self._stop_event.is_set():
            down = []
            for name in self._service_names:
                slug = slugify(name)
                try:
                    status = psutil.win_service_get(name).as_dict().get("status", "unknown")
                except psutil.NoSuchProcess:
                    status = "not_found"
                except Exception as e:
                    status = "unknown"
                    print(f"TuxD-Win: could not query service {name!r}: {e!r}")
                running = status == "running"
                if not running and status != "unknown":
                    down.append(name)
                self.publish(f"{self.base_topic}/service_{slug}_running", "ON" if running else "OFF")
                self.publish(f"{self.base_topic}/service_{slug}_attrs", json.dumps({"status": status}))
            if hasattr(self, "set_standing"):
                reason = f"Services not running: {', '.join(down)}"[:250] if down else ""
                for level in ("warning", "error"):
                    self.set_standing(level, "windows_services", reason if level == self._services_alert else "")
            self._stop_event.wait(timeout=self._services_interval)
