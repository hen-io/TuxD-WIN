import os
import datetime
import time
import threading


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
