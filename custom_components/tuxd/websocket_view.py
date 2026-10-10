import json
import logging

from aiohttp import web, WSMsgType

from homeassistant.components.http import HomeAssistantView

from .const import WS_PATH

_LOGGER = logging.getLogger(__name__)

_MAX_DEVICE_ID_LEN = 128


def _valid_device_id(device_id):
    if not isinstance(device_id, str) or not (1 <= len(device_id) <= _MAX_DEVICE_ID_LEN):
        return False
    return not any(ord(c) < 0x20 or ord(c) == 0x7F for c in device_id)


_MAX_MSG_SIZE = 16 * 1024


class TuxdWebSocketView(HomeAssistantView):

    url = WS_PATH
    name = "api:tuxd:ws"
    requires_auth = False

    def __init__(self, hub):
        self.hub = hub

    async def get(self, request):
        ws = web.WebSocketResponse(max_msg_size=_MAX_MSG_SIZE)
        await ws.prepare(request)

        device_id = None
        connected = False
        try:
            hello_raw = await ws.receive_str(timeout=10)
            hello = json.loads(hello_raw)

            if hello.get("type") != "hello":
                _LOGGER.debug("TuxD: first message on a new connection wasn't a hello - closing")
                await ws.send_str(json.dumps({"type": "error", "message": "expected hello"}))
                await ws.close()
                return ws

            candidate_id = hello.get("device_id")
            auth_result = (
                self.hub.check_auth(candidate_id, hello.get("auth"))
                if _valid_device_id(candidate_id)
                else "rejected"
            )

            if auth_result == "pending":
                await self.hub.record_pending(candidate_id, hello, hello.get("auth"))
                await ws.send_str(json.dumps({"type": "error", "message": "authentication failed"}))
                await ws.close()
                return ws

            if auth_result != "ok":
                _LOGGER.warning(
                    "TuxD: device %s failed authentication - closing connection", candidate_id
                )
                await ws.send_str(json.dumps({"type": "error", "message": "authentication failed"}))
                await ws.close()
                return ws

            device_id = candidate_id
            await self.hub.async_device_connected(device_id, hello)
            self.hub.async_set_ws(device_id, ws)
            connected = True
            await ws.send_str(json.dumps({"type": "hello_ack"}))

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self.hub.async_handle_message(device_id, msg.data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSING):
                    break
        except TimeoutError:
            _LOGGER.info(
                "TuxD: timed out waiting for a hello on a new connection (device=%s)", device_id
            )
        except ConnectionResetError:
            _LOGGER.debug("TuxD: connection reset (device=%s)", device_id)
        except Exception:
            _LOGGER.exception("Unexpected error on TuxD websocket connection (device=%s)", device_id)
        finally:
            if connected:
                self.hub.async_device_disconnected(device_id, ws)

        return ws
