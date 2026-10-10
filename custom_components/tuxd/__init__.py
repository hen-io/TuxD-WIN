import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntryType

from .config_editor import async_setup_config_editor
from .const import DOMAIN, HUB_IDENTIFIER, IMAGES_URL_PREFIX, ISSUE_PENDING_DEVICES, PLATFORMS
from .hub import TuxdHub
from .live_tty import async_setup_live_tty
from .websocket_view import TuxdWebSocketView

_LOGGER = logging.getLogger(__name__)

_VIEW_KEY = f"{DOMAIN}_ws_view"
_LIVE_TTY_KEY = f"{DOMAIN}_live_tty"
_CONFIG_EDITOR_KEY = f"{DOMAIN}_config_editor"
_IMAGES_KEY = f"{DOMAIN}_images"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = TuxdHub(hass, entry)
    await hub.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, HUB_IDENTIFIER)},
        name="TuxD",
        manufacturer="Henrik Isefjær Olsen",
        model="TuxD Home Assistant Integration",
        entry_type=DeviceEntryType.SERVICE,
    )

    view = hass.data.get(_VIEW_KEY)
    if view is None:
        view = TuxdWebSocketView(hub)
        hass.http.register_view(view)
        hass.data[_VIEW_KEY] = view
    else:
        view.hub = hub

    if not hass.data.get(_LIVE_TTY_KEY):
        async_setup_live_tty(hass)
        hass.data[_LIVE_TTY_KEY] = True

    if not hass.data.get(_CONFIG_EDITOR_KEY):
        async_setup_config_editor(hass)
        hass.data[_CONFIG_EDITOR_KEY] = True

    if not hass.data.get(_IMAGES_KEY):
        images_dir = Path(__file__).parent / "images"
        await hass.http.async_register_static_paths([
            StaticPathConfig(IMAGES_URL_PREFIX, str(images_dir), True)
        ])
        hass.data[_IMAGES_KEY] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        ir.async_delete_issue(hass, DOMAIN, ISSUE_PENDING_DEVICES)
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    hub = hass.data[DOMAIN][entry.entry_id]
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == HUB_IDENTIFIER:
            return False
        await hub.remove_device(identifier)
    return True
