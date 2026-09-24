import re

import psutil

from .shared import slugify


class DisksMixin:
    """Per-drive storage sensors plus the combined storage_used_gb/
    storage_free_gb/storage_used_pct across every monitored drive.

    Per-drive sensors mirror TuxD (Linux agent)'s per-disk ones for a disk
    named "root" (disk_root_used_space -> sensor.<host>_root_storage_used,
    ..._root_storage_used_gb, ..._root_free_space) - C:\\ is that "root"
    drive here, every other drive is named by its letter (D:\\ ->
    sensor.<host>_d_storage_used). Same object_ids as Linux, so the entities
    are interchangeable across the fleet. No per-drive I/O rates or SMART -
    "lite" skips those.

    The combined sensors keep the same object_ids and the same explicit
    ha_object_id overrides on the two _gb sensors as TuxD's host-wide
    combined sensors, for the same reason (entity_object_id() strips the
    "_gb"/"_pct" unit suffix, and without the override both _gb sensors
    would collapse to the identical entity_id "storage_used" - a real
    collision this project already fixed once on the Linux side). They stay
    registered even with a single drive (unlike Linux, which only registers
    them for 2+ disks) so existing entity ids never disappear.
    """

    def init_disks(self):
        disk_cfg = self.config.get("disks", {}) or {}
        self._disks_enabled = bool(disk_cfg.get("enabled", True))
        self._disks_interval = float(disk_cfg.get("update_interval", 60))
        self._disk_drives = disk_cfg.get("drives") or self._autodetect_drives()
        self._disk_named = self._name_drives(self._disk_drives)

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

    @staticmethod
    def _drive_identity(entry):
        # "C:", "c:\\", "C:/" all mean the C: drive; anything else (a
        # mounted-volume folder like "E:\\data") is used as-is and named
        # from its own slug. Returns (path_to_measure, name).
        text = str(entry).strip()
        m = re.match(r"^([A-Za-z]):[\\/]*$", text)
        if m:
            letter = m.group(1).lower()
            return f"{letter.upper()}:\\", ("root" if letter == "c" else letter)
        return text, (slugify(text) or "disk")

    def _name_drives(self, drives):
        named = []
        seen = set()
        for entry in drives:
            path, name = self._drive_identity(entry)
            if name in seen:
                continue
            seen.add(name)
            named.append((path, name))
        return named

    def register_disks(self):
        if not self._disks_enabled:
            return

        for _path, name in self._disk_named:
            base = f"{self.base_topic}/disk_{name}"
            self._sensor_discovery(
                f"disk_{name}_used_space_gb", f"{name} Storage Used GB", f"{base}/used_space_gb",
                unit="GB", icon="mdi:harddisk", state_class="measurement",
                ha_object_id=f"{self.device_slug}_{name}_storage_used_gb",
            )
            self._sensor_discovery(
                f"disk_{name}_free_space_gb", f"{name} Storage Free GB", f"{base}/free_space_gb",
                unit="GB", icon="mdi:harddisk", state_class="measurement",
            )
            self._sensor_discovery(
                f"disk_{name}_used_space", f"{name} Storage Used %", f"{base}/used_space",
                unit="%", icon="mdi:harddisk", state_class="measurement",
                ha_object_id=f"{self.device_slug}_{name}_storage_used",
            )

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
        gb = 1024 ** 3
        while not self._stop_event.is_set():
            try:
                total_used = 0
                total_size = 0
                for path, name in self._disk_named:
                    try:
                        usage = psutil.disk_usage(path)
                    except Exception:
                        continue
                    total_used += usage.used
                    total_size += usage.total
                    base = f"{self.base_topic}/disk_{name}"
                    self.publish(f"{base}/used_space_gb", round(usage.used / gb, 2))
                    self.publish(f"{base}/free_space_gb", round(usage.free / gb, 2))
                    self.publish(
                        f"{base}/used_space",
                        round(usage.used / usage.total * 100, 2) if usage.total else 0,
                    )
                used_gb = total_used / gb
                free_gb = (total_size - total_used) / gb
                used_pct = (total_used / total_size * 100) if total_size else 0
                self.publish(f"{self.base_topic}/storage_used_gb", round(used_gb, 1))
                self.publish(f"{self.base_topic}/storage_free_gb", round(free_gb, 1))
                self.publish(f"{self.base_topic}/storage_used_pct", round(used_pct, 1))
            except Exception as e:
                print(f"TuxD-Win: disks_loop error: {e!r}")
            self._stop_event.wait(timeout=self._disks_interval)
