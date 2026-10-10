from homeassistant.components.text import TextEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN, HUB_IDENTIFIER, SIGNAL_OFFLINE_UPDATE_URL_CHANGED
from .entity import TuxdEntity, async_setup_dynamic_platform

_DOMAIN_KEY = "text"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdText, hub)

    async_add_entities([TuxdOfflineUpdateUrlText(hub)])


class TuxdText(TuxdEntity, TextEntity):
    @property
    def native_value(self):
        return self._entry.get("state")

    async def async_set_value(self, value: str) -> None:
        command_topic = self._config.get("command_topic") or self._config.get("cmd_t")
        self._send_command(command_topic, value)


class TuxdOfflineUpdateUrlText(TextEntity):

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "Offline Update Tarball URL"
    _attr_icon = "mdi:archive-arrow-down-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = "text"

    def __init__(self, hub):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_offline_update_url"

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})

    @property
    def native_value(self):
        return self.hub.offline_update_url

    async def async_set_value(self, value: str) -> None:
        self.hub.set_offline_update_url(value)
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_OFFLINE_UPDATE_URL_CHANGED, self.async_write_ha_state)
        )
