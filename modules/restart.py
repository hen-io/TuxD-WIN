import os
import datetime
import subprocess
import time
import threading

_POWER_BUTTONS = {
    "reboot": ("Reboot", "mdi:restart", "shutdown /r /f /t 5"),
    "shutdown": ("Shutdown", "mdi:power", "shutdown /s /f /t 5"),
}


class RestartMixin:
    def _hard_restart(self):
        os._exit(1)

    def register_restart_button(self):
        self._button_discovery(
            "restart_agent",
            "Restart TuxD-Win",
            f"{self.base_topic}/restart/set",
            icon="mdi:restart",
            entity_category="diagnostic"
        )
        self._button_discovery(
            "force_poll_agent",
            "Force Refresh All Sensors",
            f"{self.base_topic}/force_poll/set",
            icon="mdi:sync",
            entity_category="diagnostic"
        )
        self._register_power_buttons()

    def _power_cmd(self, key):
        device = self.config.get("device", {}) or {}
        return str(device.get(f"{key}_cmd") or _POWER_BUTTONS[key][2])

    def _register_power_buttons(self):
        enabled = bool((self.config.get("device", {}) or {}).get("power_buttons", True))
        for key, (name, icon, _default) in _POWER_BUTTONS.items():
            if enabled:
                self._button_discovery(
                    f"custom_button_{key}",
                    name,
                    f"{self.base_topic}/power/{key}/set",
                    icon=icon,
                )
            else:
                self.publish(self._discovery_topic("button", f"custom_button_{key}"), "", retain=True)

    def handle_power_message(self, key):
        device = self.config.get("device", {}) or {}
        if key not in _POWER_BUTTONS or not bool(device.get("power_buttons", True)):
            return
        cmd = self._power_cmd(key)

        def _run():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            print(f'TuxD-Win: {ts}: "{_POWER_BUTTONS[key][0]}" button pressed > {cmd}')
            try:
                subprocess.Popen(cmd, shell=True)
            except Exception as e:
                print(f"TuxD-Win: power command failed: {e!r}")

        threading.Thread(target=_run, daemon=True).start()

    def handle_restart_message(self):
        def _restart():
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"TuxD-Win: {ts}: Restart button pressed")
            time.sleep(1.0)
            self._hard_restart()

        threading.Thread(target=_restart, daemon=True).start()

    def handle_force_poll_message(self):
        def _force_poll():
            time.sleep(0.5)
            self._hard_restart()

        threading.Thread(target=_force_poll, daemon=True).start()
