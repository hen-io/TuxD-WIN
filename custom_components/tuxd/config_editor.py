
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


def _hub(hass: HomeAssistant):
    hubs = hass.data.get(DOMAIN) or {}
    return next(iter(hubs.values()), None)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/config/get",
    vol.Required("device_id"): str,
})
@websocket_api.async_response
async def _get(hass, connection, msg):
    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_found", "TuxD is not set up")
        return
    result = await hub.async_get_device_config(msg["device_id"])
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/config/set",
    vol.Required("device_id"): str,
    vol.Required("content"): str,
})
@websocket_api.async_response
async def _set(hass, connection, msg):
    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_found", "TuxD is not set up")
        return
    result = await hub.async_set_device_config(msg["device_id"], msg["content"])
    connection.send_result(msg["id"], result)


@callback
def async_setup_config_editor(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, _get)
    websocket_api.async_register_command(hass, _set)
