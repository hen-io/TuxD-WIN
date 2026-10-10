from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    DOMAIN,
    HUB_IDENTIFIER,
    SIGNAL_LAST_SEEN_ENABLED_CHANGED,
    SIGNAL_ONLINE_SENSORS_ENABLED_CHANGED,
)
from .entity import TuxdEntity, async_setup_dynamic_platform

_DOMAIN_KEY = "switch"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdSwitch, hub)
    async_add_entities([TuxdLastSeenSwitch(hub), TuxdOnlineSensorsSwitch(hub)])


class TuxdSwitch(TuxdEntity, SwitchEntity):
    @property
    def is_on(self):
        return self._entry.get("state") == self._config.get("payload_on", "ON")

    async def async_turn_on(self, **kwargs) -> None:
        self._send_command(self._config.get("command_topic"), self._config.get("payload_on", "ON"))

    async def async_turn_off(self, **kwargs) -> None:
        self._send_command(self._config.get("command_topic"), self._config.get("payload_off", "OFF"))


class TuxdLastSeenSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_last_seen_enabled"
        self._attr_name = "Last Seen Sensors"

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def is_on(self):
        return self.hub.last_seen_enabled

    async def async_turn_on(self, **kwargs):
        await self.hub.set_last_seen_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_last_seen_enabled(False)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LAST_SEEN_ENABLED_CHANGED,
                self.async_write_ha_state,
            )
        )


class TuxdOnlineSensorsSwitch(SwitchEntity):

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:lan-connect"

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_online_sensors_enabled"
        self._attr_name = "Online/Offline Sensors"

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def is_on(self):
        return self.hub.online_sensors_enabled

    async def async_turn_on(self, **kwargs):
        await self.hub.set_online_sensors_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.hub.set_online_sensors_enabled(False)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ONLINE_SENSORS_ENABLED_CHANGED,
                self.async_write_ha_state,
            )
        )
