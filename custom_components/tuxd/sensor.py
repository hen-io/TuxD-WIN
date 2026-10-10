from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HUB_IDENTIFIER,
    SIGNAL_DEVICE_APPROVED,
    SIGNAL_HUB_STATS_UPDATE,
    SIGNAL_LAST_SEEN_UPDATE,
    SIGNAL_LAST_SEEN_ENABLED_CHANGED,
    SIGNAL_THRESHOLDS_CHANGED,
    THRESHOLD_METRICS,
)
from .entity import TuxdEntity, async_setup_dynamic_platform
from .update import TuxdUpdate

_DOMAIN_KEY = "sensor"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdSensor, hub)

    async_add_entities([
        TuxdConfiguredDevicesSensor(hub),
        TuxdOnlineDevicesSensor(hub),
        TuxdOfflineDevicesSensor(hub),
        TuxdDevicesWithErrorsSensor(hub),
        TuxdDevicesWithHostUpdatesSensor(hub),
        TuxdDevicesWithScriptUpdatesSensor(hub),
        TuxdDevicesWithSmartErrorsSensor(hub),
        TuxdDevicesWithDockerErrorsSensor(hub),
        TuxdDevicesWithUnhealthyStacksSensor(hub),
        TuxdDevicesByVersionSensor(hub),
        *[TuxdVmsOverThresholdSensor(hub, *row) for row in THRESHOLD_METRICS],
    ])

    added = set()

    @callback
    def _add_last_seen(device_id):
        if not hub.last_seen_enabled:
            return
        if device_id in added:
            return
        added.add(device_id)
        async_add_entities([TuxdLastSeenSensor(hub, device_id)])

    @callback
    def _remove_last_seen(device_id):
        added.discard(device_id)
        ent_reg = er.async_get(hass)
        entity_id = ent_reg.async_get_entity_id(_DOMAIN_KEY, DOMAIN, f"{DOMAIN}_{device_id}_last_seen")
        if entity_id:
            ent_reg.async_remove(entity_id)

    @callback
    def _on_last_seen_enabled_changed():
        if hub.last_seen_enabled:
            for device_id in list(hub.device_keys.keys()):
                _add_last_seen(device_id)
        else:
            for device_id in list(added):
                _remove_last_seen(device_id)

    for device_id in list(hub.device_keys.keys()):
        _add_last_seen(device_id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_APPROVED, _add_last_seen)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_LAST_SEEN_ENABLED_CHANGED, _on_last_seen_enabled_changed)
    )


class TuxdSensor(TuxdEntity, SensorEntity):
    @property
    def native_value(self):
        value = self._entry.get("state")
        if isinstance(value, str):
            device_class = self._config.get("device_class")
            if device_class == "timestamp":
                return dt_util.parse_datetime(value)
            if device_class == "date":
                return dt_util.parse_date(value)
        return value

    @property
    def native_unit_of_measurement(self):
        return self._config.get("unit_of_measurement")

    @property
    def state_class(self):
        return self._config.get("state_class")

    @property
    def device_class(self):
        return self._config.get("device_class")


def _has_update(hub, unique_id):
    upd = TuxdUpdate(hub, unique_id)
    installed, latest = upd.installed_version, upd.latest_version
    return installed is not None and latest is not None and installed != latest


class TuxdHubStatSensor(SensorEntity):

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, hub, oid, name, icon):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_{oid}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_HUB_STATS_UPDATE, self.async_write_ha_state)
        )


class TuxdConfiguredDevicesSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "configured_devices", "TuxD Configured Devices", "mdi:server-network")

    @property
    def native_value(self):
        return len(self.hub.device_keys)


class TuxdOnlineDevicesSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "online_devices", "TuxD Online Devices", "mdi:server-network-outline")

    @property
    def native_value(self):
        return len(self.hub.devices)


class TuxdOfflineDevicesSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "offline_devices", "TuxD Offline Devices", "mdi:server-network-off")

    def _offline_ids(self):
        return sorted(set(self.hub.device_keys) - set(self.hub.devices))

    @property
    def native_value(self):
        return len(self._offline_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._offline_ids()}


class TuxdDevicesByVersionSensor(TuxdHubStatSensor):

    _attr_native_unit_of_measurement = "versions"

    def __init__(self, hub):
        super().__init__(hub, "devices_by_version", "TuxD Devices By Version", "mdi:tag-multiple-outline")

    def _counts(self):
        counts = {}
        for info in self.hub.devices.values():
            version = info.get("sw_version") or "unknown"
            counts[version] = counts.get(version, 0) + 1
        return counts

    @property
    def native_value(self):
        return len(self._counts())

    @property
    def extra_state_attributes(self):
        return {"versions": self._counts()}


class TuxdDevicesWithErrorsSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "devices_with_errors", "TuxD Devices With Errors", "mdi:alert-circle-outline")

    def _device_ids(self):
        return sorted({
            e.get("device_id") for e in self.hub.entities.values()
            if e.get("object_id") == "system_error" and e.get("state") == "ON"
        })

    @property
    def native_value(self):
        return len(self._device_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._device_ids()}


class TuxdDevicesWithHostUpdatesSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "devices_with_host_updates", "TuxD Devices With Host Updates", "mdi:package-up")

    def _device_ids(self):
        return sorted({
            e.get("device_id") for uid, e in self.hub.entities.items()
            if e.get("object_id") == "host_update" and _has_update(self.hub, uid)
        })

    @property
    def native_value(self):
        return len(self._device_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._device_ids()}


class TuxdDevicesWithScriptUpdatesSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "devices_with_script_updates", "TuxD Devices With TuxD Agent Updates", "mdi:script-text-outline")

    def _device_ids(self):
        return sorted({
            e.get("device_id") for uid, e in self.hub.entities.items()
            if e.get("object_id") == "self_update" and _has_update(self.hub, uid)
        })

    @property
    def native_value(self):
        return len(self._device_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._device_ids()}


class TuxdDevicesWithSmartErrorsSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "devices_with_smart_errors", "TuxD Devices With SMART Errors", "mdi:harddisk")

    def _device_ids(self):
        devices = set()
        for e in self.hub.entities.values():
            object_id = e.get("object_id") or ""
            if not (object_id.startswith("disk_") and object_id.endswith("_smart_errors")):
                continue
            try:
                if float(e.get("state")) > 0:
                    devices.add(e.get("device_id"))
            except (TypeError, ValueError):
                continue
        return sorted(devices)

    @property
    def native_value(self):
        return len(self._device_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._device_ids()}


class TuxdDevicesWithDockerErrorsSensor(TuxdHubStatSensor):
    def __init__(self, hub):
        super().__init__(hub, "devices_with_docker_errors", "TuxD Devices With Docker Errors", "mdi:docker")

    def _device_ids(self):
        return sorted({
            e.get("device_id") for e in self.hub.entities.values()
            if e.get("object_id") == "docker_containers_error" and e.get("state") == "ON"
        })

    @property
    def native_value(self):
        return len(self._device_ids())

    @property
    def extra_state_attributes(self):
        return {"devices": self._device_ids()}


class TuxdDevicesWithUnhealthyStacksSensor(TuxdHubStatSensor):

    _NOT_A_PROBLEM = ("healthy", "unknown", "unavailable", "")

    def __init__(self, hub):
        super().__init__(hub, "devices_with_unhealthy_stacks", "TuxD Devices With Unhealthy Stacks", "mdi:ferry")

    @staticmethod
    def _is_stack_health(e):
        object_id = e.get("object_id") or ""
        return object_id.startswith("tugboat_") and object_id.endswith("_health")

    def _scan(self):
        stacks = {}
        total = 0
        for e in self.hub.entities.values():
            if not self._is_stack_health(e):
                continue
            total += 1
            health = str(e.get("state") or "").strip().lower()
            if health in self._NOT_A_PROBLEM:
                continue
            name = str((e.get("config") or {}).get("name") or e.get("object_id"))
            for suffix in (" Health", " Helse"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            stacks.setdefault(e.get("device_id"), {})[name] = health
        return stacks, total

    @property
    def native_value(self):
        return len(self._scan()[0])

    @property
    def extra_state_attributes(self):
        stacks, total = self._scan()
        return {"devices": sorted(stacks), "stacks": stacks, "stacks_total": total}


class TuxdVmsOverThresholdSensor(TuxdHubStatSensor):

    def __init__(self, hub, object_id, name, icon, unit, min_value, max_value, step, default):
        super().__init__(hub, f"vms_over_{object_id}", f"TuxD VMs Over {name} Threshold", icon)
        self._object_id = object_id
        self._default = default

    def _over_values(self):
        threshold = self.hub.thresholds.get(self._object_id, self._default)
        values = {}
        for e in self.hub.entities.values():
            if e.get("object_id") != self._object_id:
                continue
            try:
                value = float(e.get("state"))
            except (TypeError, ValueError):
                continue
            if value > threshold:
                values[e.get("device_id")] = value
        return values

    @property
    def native_value(self):
        return len(self._over_values())

    @property
    def extra_state_attributes(self):
        values = self._over_values()
        return {"devices": sorted(values.keys()), "values": values}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_THRESHOLDS_CHANGED, self.async_write_ha_state)
        )


class TuxdLastSeenSensor(SensorEntity):

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, hub, device_id):
        self.hub = hub
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_last_seen"
        self._attr_name = f"{device_id} Last Seen"

    @property
    def native_value(self):
        return self.hub.device_last_seen.get(self._device_id)

    @property
    def available(self):
        return self.hub.last_seen_enabled

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LAST_SEEN_UPDATE.format(device_id=self._device_id),
                self.async_write_ha_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LAST_SEEN_ENABLED_CHANGED,
                self.async_write_ha_state,
            )
        )
