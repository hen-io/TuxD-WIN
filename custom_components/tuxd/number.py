from homeassistant.components.number import NumberEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    DOMAIN,
    HUB_IDENTIFIER,
    SIGNAL_LAST_SEEN_UPDATE_INTERVAL_CHANGED,
    SIGNAL_ONLINE_TIMEOUT_CHANGED,
    SIGNAL_THRESHOLDS_CHANGED,
    THRESHOLD_METRICS,
)
from .entity import TuxdEntity, async_setup_dynamic_platform

_DOMAIN_KEY = "number"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdNumber, hub)

    async_add_entities([
        TuxdThresholdNumber(hub, *row) for row in THRESHOLD_METRICS
    ])
    async_add_entities([TuxdOnlineTimeoutNumber(hub)])
    async_add_entities([TuxdLastSeenUpdateIntervalNumber(hub)])


class TuxdNumber(TuxdEntity, NumberEntity):
    @property
    def native_value(self):
        state = self._entry.get("state")
        try:
            return float(state)
        except (TypeError, ValueError):
            return None

    @property
    def native_min_value(self):
        return self._config.get("min", 0)

    @property
    def native_max_value(self):
        return self._config.get("max", 100)

    @property
    def native_step(self):
        return self._config.get("step", 1)

    @property
    def native_unit_of_measurement(self):
        return self._config.get("unit_of_measurement")

    async def async_set_native_value(self, value: float) -> None:
        self._send_command(self._config.get("command_topic"), str(value))


class TuxdThresholdNumber(NumberEntity):

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0

    def __init__(self, hub, object_id, name, icon, unit, min_value, max_value, step, default):
        self.hub = hub
        self._object_id = object_id
        self._default = default
        self._attr_unique_id = f"{DOMAIN}_hub_threshold_{object_id}"
        self._attr_name = f"{name} Threshold"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def native_value(self):
        return self.hub.thresholds.get(self._object_id, self._default)

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.set_threshold(self._object_id, value)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_THRESHOLDS_CHANGED, self.async_write_ha_state)
        )


class TuxdOnlineTimeoutNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 10
    _attr_native_max_value = 86400
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_online_timeout"
        self._attr_name = "Online Timeout"

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def native_value(self):
        return self.hub.online_timeout

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.set_online_timeout(value)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ONLINE_TIMEOUT_CHANGED,
                self.async_write_ha_state,
            )
        )


class TuxdLastSeenUpdateIntervalNumber(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 3600
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:timer-refresh-outline"

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_last_seen_update_interval"
        self._attr_name = "Last Seen Update Interval"

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def native_value(self):
        return self.hub.last_seen_update_interval

    async def async_set_native_value(self, value: float) -> None:
        await self.hub.set_last_seen_update_interval(value)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LAST_SEEN_UPDATE_INTERVAL_CHANGED,
                self.async_write_ha_state,
            )
        )
