import time
import psutil


class NetworkMixin:

    def init_network(self):
        network_cfg = self.config.get("network", {}) or {}
        self._network_enabled = bool(network_cfg.get("enabled", True))
        self._network_interval = float(network_cfg.get("update_interval", 5))

    def register_network(self):
        if not self._network_enabled:
            return
        self._sensor_discovery(
            "network_in_mbps", "Network in", f"{self.base_topic}/network_in_mbps",
            unit="Mbit/s", icon="mdi:download-network", state_class="measurement",
        )
        self._sensor_discovery(
            "network_out_mbps", "Network out", f"{self.base_topic}/network_out_mbps",
            unit="Mbit/s", icon="mdi:upload-network", state_class="measurement",
        )
        self._sensor_discovery(
            "network_in_out", "Network in/out", f"{self.base_topic}/network_in_out",
            unit="Mbit/s", icon="mdi:lan", state_class="measurement",
        )

    def network_loop(self):
        if not self._network_enabled:
            return
        try:
            prev = psutil.net_io_counters()
        except Exception:
            return
        prev_time = time.monotonic()
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._network_interval)
            if self._stop_event.is_set():
                return
            try:
                current = psutil.net_io_counters()
                now = time.monotonic()
                elapsed = max(now - prev_time, 0.001)
                rx_mbps = max((current.bytes_recv - prev.bytes_recv) * 8 / elapsed / 1_000_000, 0)
                tx_mbps = max((current.bytes_sent - prev.bytes_sent) * 8 / elapsed / 1_000_000, 0)
                prev, prev_time = current, now
                self.publish(f"{self.base_topic}/network_in_mbps", round(rx_mbps, 2))
                self.publish(f"{self.base_topic}/network_out_mbps", round(tx_mbps, 2))
                self.publish(f"{self.base_topic}/network_in_out", round(rx_mbps + tx_mbps, 2))
            except Exception as e:
                print(f"TuxD-Win: network_loop error: {e!r}")
