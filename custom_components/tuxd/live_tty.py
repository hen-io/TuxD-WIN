
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


def _hub(hass: HomeAssistant):
    hubs = hass.data.get(DOMAIN) or {}
    return next(iter(hubs.values()), None)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/live_tty/open",
    vol.Required("device_id"): str,
    vol.Optional("cols", default=80): int,
    vol.Optional("rows", default=24): int,
    vol.Optional("password"): str,
})
@callback
def _open(hass, connection, msg):
    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_found", "TuxD is not set up")
        return
    session_id = hub.tty_open(
        msg["device_id"], connection, msg["id"], msg["cols"], msg["rows"], msg.get("password")
    )
    if session_id is None:
        connection.send_error(msg["id"], "not_found", f"{msg['device_id']} is not connected")
        return

    @callback
    def _unsub():
        hub.tty_close(session_id)

    connection.subscriptions[msg["id"]] = _unsub
    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(msg["id"], {"type": "tty_session", "session": session_id})
    )


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/live_tty/input",
    vol.Required("session"): str,
    vol.Required("data"): str,
})
@callback
def _input(hass, connection, msg):
    hub = _hub(hass)
    if hub is not None:
        hub.tty_input(msg["session"], msg["data"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/live_tty/resize",
    vol.Required("session"): str,
    vol.Required("cols"): int,
    vol.Required("rows"): int,
})
@callback
def _resize(hass, connection, msg):
    hub = _hub(hass)
    if hub is not None:
        hub.tty_resize(msg["session"], msg["cols"], msg["rows"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "tuxd/live_tty/close",
    vol.Required("session"): str,
})
@callback
def _close(hass, connection, msg):
    hub = _hub(hass)
    if hub is not None:
        hub.tty_close(msg["session"])
    connection.send_result(msg["id"])


@callback
def async_setup_live_tty(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, _open)
    websocket_api.async_register_command(hass, _input)
    websocket_api.async_register_command(hass, _resize)
    websocket_api.async_register_command(hass, _close)
