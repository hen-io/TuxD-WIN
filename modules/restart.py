import os
import datetime
import time
import threading


class RestartMixin:
    def _hard_restart(self):
        # NOT os.execv() here, unlike TuxD (Linux agent)'s restart.py -
        # Windows has no real exec()-family syscall, so CPython emulates
        # os.execv on Windows by spawning the child and then BLOCKING the
        # calling thread until that child exits (effectively os.execv ==
        # os.spawnv(P_WAIT, ...) + sys.exit() on this platform). Since the
        # child here is this same long-running agent, that would hang
        # whichever thread called this (a button handler, the connection
        # thread) forever instead of actually restarting.
        #
        # Self-spawning a detached replacement (the other obvious fix) was
        # tried and dropped: install-windows.ps1 sets up a Scheduled Task
        # with its own restart-on-exit policy, and racing that against a
        # process this code also spawned itself risks two live agents
        # fighting over the same device_id. A plain nonzero exit is both
        # simpler and exactly what TuxD's own restart.py already falls back
        # to when execv itself fails ("exiting instead so the service
        # supervisor restarts us") - here it's not a fallback, it's the
        # only path, and the Scheduled Task is that supervisor.
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
        # Every sensor loop does its first poll immediately on startup,
        # before its first interval wait - so a plain restart already
        # forces "poll everything now" for free, same reasoning as TuxD's
        # own force_poll button.
        def _force_poll():
            time.sleep(0.5)
            self._hard_restart()

        threading.Thread(target=_force_poll, daemon=True).start()
