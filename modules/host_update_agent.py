import json
import threading

from .shared import run_powershell

_UPDATE_CHECK_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "try { "
    "$s = New-Object -ComObject Microsoft.Update.Session; "
    "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); "
    "Write-Output $r.Updates.Count "
    "} catch { Write-Output '-1' }"
)


class HostUpdateMixin:

    def init_host_update(self):
        cfg = self.config.get("host_update", {}) or {}
        self._host_update_enabled = bool(cfg.get("enabled", True))
        self._host_update_interval = float(cfg.get("check_interval", 3600))
        self._host_update_last_count = None
        self._host_update_checking = False

    def register_host_update(self):
        if not self._host_update_enabled:
            return
        self._update_discovery(
            "host_update",
            "Windows Updates",
            f"{self.base_topic}/host_update/state",
            icon="mdi:microsoft-windows",
            entity_category="diagnostic",
        )
        self._button_discovery(
            "host_update_check",
            "Check Windows Updates",
            f"{self.base_topic}/host_update/check/set",
            icon="mdi:cloud-refresh",
            entity_category="diagnostic",
        )
        self._sensor_discovery(
            "status_updates_available",
            "Updates Available",
            f"{self.base_topic}/updates_available",
            icon="mdi:package-up",
        )
        if self._host_update_last_count is None:
            self._publish_host_update_state(0, in_progress=False)

    def _publish_host_update_state(self, count, in_progress):
        if count and count > 0:
            installed, latest = "Up to date", f"{count} update(s) available"
        else:
            installed = latest = "Up to date"
        state = {
            "installed_version": installed,
            "latest_version": latest,
            "title": "Windows Updates",
            "in_progress": in_progress,
        }
        self.publish(f"{self.base_topic}/host_update/state", json.dumps(state), retain=True)

    def handle_host_update_check(self):
        threading.Thread(target=self._run_host_update_check, daemon=True).start()

    def _run_host_update_check(self):
        if self._host_update_checking:
            return
        self._host_update_checking = True
        self._publish_host_update_state(self._host_update_last_count or 0, in_progress=True)
        count = -1
        try:
            output = run_powershell(_UPDATE_CHECK_SCRIPT, timeout=180)
            lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
            if lines:
                count = int(lines[-1])
        except Exception as e:
            print(f"TuxD-Win: Windows Update check failed: {e!r}")
        finally:
            self._host_update_checking = False
        if count >= 0:
            self._host_update_last_count = count
            self.publish(f"{self.base_topic}/updates_available", f"{count} new updates")
        self._publish_host_update_state(max(self._host_update_last_count or 0, 0), in_progress=False)

    def host_update_loop(self):
        if not self._host_update_enabled:
            return
        while not self._stop_event.is_set():
            self._run_host_update_check()
            self._stop_event.wait(timeout=self._host_update_interval)
