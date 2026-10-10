from homeassistant.components.select import SelectEntity

from .const import DOMAIN
from .entity import TuxdEntity, async_setup_dynamic_platform

_DOMAIN_KEY = "select"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdSelect, hub)


class TuxdSelect(TuxdEntity, SelectEntity):
    @property
    def current_option(self):
        return self._entry.get("state")

    @property
    def options(self):
        return self._config.get("options") or []

    async def async_select_option(self, option: str) -> None:
        self._send_command(self._config.get("command_topic"), option)
