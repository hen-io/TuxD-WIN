import psutil


class DisksMixin:
    """Combined storage_used_gb/storage_free_gb/storage_used_pct across
    every monitored drive - same object_ids and the same explicit
    ha_object_id overrides on the two _gb sensors as TuxD (Linux agent)'s
    disks_agent.py uses for its host-wide combined sensors, for the same
    reason (entity_object_id() strips the "_gb"/"_pct" unit suffix, and
    without the override both _gb sensors would collapse to the identical
    entity_id "storage_used" - a real collision this project already fixed
    once on the Linux side). No per-disk SMART data - "lite" skips it, and
    smartctl-equivalent tooling isn't a safe assumption on a Windows host.
    """

    def init_disks(self):
        disk_cfg = self.config.get("disks", {}) or {}
        self._disks_enabled = bool(disk_cfg.get("enabled", True))
        self._disks_interval = float(disk_cfg.get("update_interval", 60))
        self._disk_drives = disk_cfg.get("drives") or self._autodetect_drives()

    def _autodetect_drives(self):
        drives = []
        try:
            for part in psutil.disk_partitions(all=False):
                if not part.fstype or "cdrom" in (part.opts or "").lower():
                    continue
                drives.append(part.mountpoint)
        except Exception:
            pass
        return drives or ["C:\\"]

    def register_disks(self):
        if not self._disks_enabled:
            return
        self._sensor_discovery(
            "storage_used_gb", "Storage Used GB", f"{self.base_topic}/storage_used_gb",
            unit="GB", icon="mdi:harddisk", state_class="measurement",
            ha_object_id=f"{self.device_slug}_storage_used_gb",
        )
        self._sensor_discovery(
            "storage_free_gb", "Storage Free GB", f"{self.base_topic}/storage_free_gb",
            unit="GB", icon="mdi:harddisk", state_class="measurement",
            ha_object_id=f"{self.device_slug}_storage_free_gb",
        )
        self._sensor_discovery(
            "storage_used_pct", "Storage Used Percent", f"{self.base_topic}/storage_used_pct",
            unit="%", icon="mdi:harddisk", state_class="measurement",
        )

    def disks_loop(self):
        if not self._disks_enabled:
            return
        while not self._stop_event.is_set():
            try:
                total_used = 0
                total_size = 0
                for drive in self._disk_drives:
                    try:
                        usage = psutil.disk_usage(drive)
                    except Exception:
                        continue
                    total_used += usage.used
                    total_size += usage.total
                used_gb = total_used / (1024 ** 3)
                free_gb = (total_size - total_used) / (1024 ** 3)
                used_pct = (total_used / total_size * 100) if total_size else 0
                self.publish(f"{self.base_topic}/storage_used_gb", round(used_gb, 1))
                self.publish(f"{self.base_topic}/storage_free_gb", round(free_gb, 1))
                self.publish(f"{self.base_topic}/storage_used_pct", round(used_pct, 1))
            except Exception as e:
                print(f"TuxD-Win: disks_loop error: {e!r}")
            self._stop_event.wait(timeout=self._disks_interval)
