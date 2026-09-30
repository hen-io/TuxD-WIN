import json

import psutil

from .shared import slugify


class ServicesMixin:

    def init_services(self):
        services_cfg = self.config.get("services", {}) or {}
        self._services_enabled = bool(services_cfg.get("enabled", True))
        self._services_interval = float(services_cfg.get("update_interval", 30))
        self._service_names = [str(n) for n in (services_cfg.get("names") or [])]

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
                self.publish(f"{self.base_topic}/service_{slug}_running", "ON" if running else "OFF")
                self.publish(f"{self.base_topic}/service_{slug}_attrs", json.dumps({"status": status}))
            self._stop_event.wait(timeout=self._services_interval)
