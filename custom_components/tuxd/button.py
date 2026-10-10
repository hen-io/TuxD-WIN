from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN, HUB_IDENTIFIER
from .entity import TuxdEntity, async_setup_dynamic_platform

_DOMAIN_KEY = "button"


async def async_setup_entry(hass, entry, async_add_entities):
    hub = hass.data[DOMAIN][entry.entry_id]
    async_setup_dynamic_platform(hass, entry, async_add_entities, _DOMAIN_KEY, TuxdButton, hub)

    async_add_entities([
        TuxdRestartAllButton(hub),
        TuxdRefreshAllButton(hub),
        TuxdUpdateAllButton(hub),
        TuxdCheckHostUpdatesAllButton(hub),
    ])


class TuxdButton(TuxdEntity, ButtonEntity):
    async def async_press(self) -> None:
        self._send_command(self._config.get("command_topic"), "PRESS")


class TuxdHubButton(ButtonEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub, oid, name, icon):
        self.hub = hub
        self._attr_unique_id = f"{DOMAIN}_hub_{oid}"
        self._attr_name = name
        self._attr_icon = icon

    @property
    def device_info(self):
        return DeviceInfo(identifiers={(DOMAIN, HUB_IDENTIFIER)})


class TuxdRestartAllButton(TuxdHubButton):
    def __init__(self, hub):
        super().__init__(hub, "restart_all", "Restart All Device Agents", "mdi:restart")

    async def async_press(self) -> None:
        self.hub.restart_all_devices()


class TuxdRefreshAllButton(TuxdHubButton):
    def __init__(self, hub):
        super().__init__(hub, "refresh_all", "Refresh Sensor Data On All Device Agents", "mdi:sync")

    async def async_press(self) -> None:
        self.hub.refresh_all_devices()


class TuxdUpdateAllButton(TuxdHubButton):
    def __init__(self, hub):
        super().__init__(hub, "update_all", "Update All Device Agents", "mdi:cloud-download")

    async def async_press(self) -> None:
        self.hub.update_all_devices()


class TuxdCheckHostUpdatesAllButton(TuxdHubButton):
    def __init__(self, hub):
        super().__init__(hub, "check_host_updates_all", "Check Host Updates On All Devices", "mdi:server-security")

    async def async_press(self) -> None:
        self.hub.check_host_updates_all_devices()
