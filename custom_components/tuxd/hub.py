import asyncio
import base64
import json
import logging
import re
import secrets
import time
import uuid

from homeassistant.components import websocket_api
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HUB_IDENTIFIER,
    ISSUE_PENDING_DEVICES,
    LAST_SEEN_UPDATE_INTERVAL_DEFAULT,
    ONLINE_TIMEOUT_DEFAULT,
    PLATFORMS,
    SIGNAL_DEVICE_APPROVED,
    SIGNAL_HUB_STATS_UPDATE,
    SIGNAL_LAST_SEEN_UPDATE,
    SIGNAL_LAST_SEEN_UPDATE_INTERVAL_CHANGED,
    SIGNAL_LAST_SEEN_ENABLED_CHANGED,
    SIGNAL_NEW_ENTITY,
    SIGNAL_OFFLINE_UPDATE_URL_CHANGED,
    SIGNAL_ONLINE_SENSORS_ENABLED_CHANGED,
    SIGNAL_ONLINE_TIMEOUT_CHANGED,
    SIGNAL_REMOVE_ENTITY,
    SIGNAL_STATE_UPDATE,
    SIGNAL_THRESHOLDS_CHANGED,
    THRESHOLD_METRICS,
)

_THRESHOLD_OBJECT_IDS = frozenset(row[0] for row in THRESHOLD_METRICS)

_LOGGER = logging.getLogger(__name__)

_MAX_PENDING_DEVICES = 50


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r")


def _strip_ansi(text):
    return _ANSI_ESCAPE_RE.sub("", text)


class _HeadlessTtyCollector:

    def __init__(self):
        self.output = []
        self.exit_event = asyncio.Event()
        self.exit_code = None
        self.exit_reason = None

    def send_message(self, message):
        event = message.get("event") or {}
        etype = event.get("type")
        if etype == "tty_data":
            try:
                raw = base64.b64decode(event.get("data") or "")
            except Exception:
                raw = b""
            self.output.append(raw.decode("utf-8", errors="replace"))
        elif etype == "tty_exit":
            self.exit_code = event.get("code")
            self.exit_reason = event.get("reason")
            self.exit_event.set()


def _is_stats_relevant_object_id(object_id):
    object_id = object_id or ""
    return (
        object_id in ("system_error", "host_update", "self_update", "docker_containers_error")
        or object_id in _THRESHOLD_OBJECT_IDS
        or (object_id.startswith("disk_") and object_id.endswith("_smart_errors"))
        or (object_id.startswith("tugboat_") and object_id.endswith("_health"))
    )


class TuxdHub:

    _RECONCILE_SETTLE_SECONDS = 10.0

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")
        self.pairing_key = ""
        self.device_keys = {}
        self.pending_devices = {}
        self.thresholds = {}
        self.online_timeout = ONLINE_TIMEOUT_DEFAULT
        self.last_seen_enabled = True
        self.online_sensors_enabled = True
        self.last_seen_update_interval = LAST_SEEN_UPDATE_INTERVAL_DEFAULT

        self.devices = {}
        self.device_last_seen = {}
        self._last_seen_dispatched = {}
        self.entities = {}
        self.key_to_unique_ids = {}
        self._device_generation = {}
        self._tty_sessions = {}
        self._config_requests = {}
        self.offline_update_url = ""

    async def async_load(self):
        stored = await self._store.async_load()
        if stored is not None:
            self.pairing_key = stored.get("pairing_key", "")
            self.device_keys = dict(stored.get("device_keys", {}))
            self.pending_devices = dict(stored.get("pending_devices", {}))
            self.thresholds = dict(stored.get("thresholds", {}))
            online_timeout_raw = stored.get("online_timeout", ONLINE_TIMEOUT_DEFAULT)
            needs_timeout_migration = "online_timeout" in stored and not stored.get("online_timeout_is_seconds")
            if needs_timeout_migration:
                online_timeout_raw = int(online_timeout_raw) * 60
            self.online_timeout = max(10, min(86400, int(online_timeout_raw)))
            self.last_seen_enabled = bool(stored.get("last_seen_enabled", True))
            self.online_sensors_enabled = bool(stored.get("online_sensors_enabled", True))
            self.last_seen_update_interval = max(1, min(3600, int(stored.get("last_seen_update_interval", LAST_SEEN_UPDATE_INTERVAL_DEFAULT))))
            if needs_timeout_migration:
                await self._persist()
        else:
            self.pairing_key = self.entry.data.get("pairing_key", "")
            self.device_keys = dict(self.entry.data.get("device_keys", {}))
            self.pending_devices = dict(self.entry.data.get("pending_devices", {}))
            online_timeout_raw = self.entry.data.get("online_timeout", ONLINE_TIMEOUT_DEFAULT)
            if "online_timeout" in self.entry.data:
                online_timeout_raw = int(online_timeout_raw) * 60
            self.online_timeout = max(10, min(86400, int(online_timeout_raw)))
            self.last_seen_enabled = bool(self.entry.data.get("last_seen_enabled", True))
            self.online_sensors_enabled = bool(self.entry.data.get("online_sensors_enabled", True))
            self.last_seen_update_interval = max(1, min(3600, int(self.entry.data.get("last_seen_update_interval", LAST_SEEN_UPDATE_INTERVAL_DEFAULT))))
            await self._persist()

        self._sync_pending_issue()


    def check_auth(self, device_id, presented_key):
        if not device_id or not presented_key:
            return "rejected"
        known_key = self.device_keys.get(device_id)
        if known_key is not None:
            return "ok" if secrets.compare_digest(presented_key, known_key) else "rejected"
        return "pending"

    async def record_pending(self, device_id, hello, presented_key=None):
        await self._resync()
        if device_id not in self.pending_devices and len(self.pending_devices) >= _MAX_PENDING_DEVICES:
            _LOGGER.warning(
                "TuxD: pending-devices list is full (%d) - ignoring pairing attempt from %s",
                _MAX_PENDING_DEVICES, device_id,
            )
            return
        self.pending_devices[device_id] = {
            "model": hello.get("model"),
            "sw_version": hello.get("sw_version"),
            "presented_key": presented_key,
        }
        await self._persist()
        self._sync_pending_issue()
        _LOGGER.info("TuxD: device %s is awaiting approval", device_id)

    async def approve_device(self, device_id):
        await self._resync()
        if device_id not in self.pending_devices:
            return None
        new_key = secrets.token_hex(32)
        self.device_keys[device_id] = new_key
        self.pending_devices.pop(device_id, None)
        await self._persist()
        self._sync_pending_issue()
        _LOGGER.info("TuxD: device %s approved and issued its own key", device_id)
        self._notify_stats_changed()
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_APPROVED, device_id)
        return new_key

    async def trust_device_key(self, device_id):
        await self._resync()
        info = self.pending_devices.get(device_id)
        if not info:
            return None
        presented_key = info.get("presented_key")
        if not presented_key or presented_key == self.pairing_key:
            return None
        self.device_keys[device_id] = presented_key
        self.pending_devices.pop(device_id, None)
        await self._persist()
        self._sync_pending_issue()
        _LOGGER.info("TuxD: device %s approved, trusting the key it already presented", device_id)
        self._notify_stats_changed()
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_APPROVED, device_id)
        return presented_key

    async def set_device_key(self, device_id, key):
        await self._resync()
        key = (key or "").strip()
        if not key:
            return False, "empty"
        for other_id, other_key in self.device_keys.items():
            if other_id != device_id and secrets.compare_digest(other_key, key):
                return False, "collision"
        self.device_keys[device_id] = key
        self.pending_devices.pop(device_id, None)
        await self._persist()
        self._sync_pending_issue()
        _LOGGER.info("TuxD: device %s given a manually-set key", device_id)
        self._notify_stats_changed()
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_APPROVED, device_id)
        return True, None

    async def rotate_device_key(self, device_id):
        await self._resync()
        if device_id not in self.device_keys:
            return None
        new_key = secrets.token_hex(32)
        self.device_keys[device_id] = new_key
        await self._persist()
        _LOGGER.info("TuxD: device %s issued a new key", device_id)
        return new_key

    async def reject_device(self, device_id):
        await self._resync()
        if device_id in self.pending_devices:
            self.pending_devices.pop(device_id, None)
            await self._persist()
            self._sync_pending_issue()

    def _sync_pending_issue(self):
        if self.pending_devices:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_PENDING_DEVICES,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_PENDING_DEVICES,
                translation_placeholders={"count": str(len(self.pending_devices))},
                data={"entry_id": self.entry.entry_id},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_PENDING_DEVICES)

    async def revoke_device(self, device_id):
        await self._resync()
        if device_id in self.device_keys:
            self.device_keys.pop(device_id, None)
            await self._persist()
            self._notify_stats_changed()

    async def remove_device(self, device_id):
        await self.revoke_device(device_id)
        self.device_last_seen.pop(device_id, None)
        if device_id in self.pending_devices:
            self.pending_devices.pop(device_id, None)
            await self._persist()
            self._sync_pending_issue()

        info = self.devices.pop(device_id, None)
        if info and info.get("ws") is not None:
            asyncio.create_task(info["ws"].close())

        stale = [(uid, e.get("domain")) for uid, e in self.entities.items() if e.get("device_id") == device_id]
        for uid, domain in stale:
            self.entities.pop(uid, None)
            if domain:
                async_dispatcher_send(self.hass, SIGNAL_REMOVE_ENTITY.format(domain=domain), uid)
        for uids in self.key_to_unique_ids.values():
            uids.difference_update(uid for uid, _domain in stale)

        self._notify_stats_changed()

    def _touch_last_seen(self, device_id):
        self.device_last_seen[device_id] = dt_util.utcnow()
        now = time.monotonic()
        last_dispatch = self._last_seen_dispatched.get(device_id, 0.0)
        if now - last_dispatch < self.last_seen_update_interval:
            return
        self._last_seen_dispatched[device_id] = now
        async_dispatcher_send(self.hass, SIGNAL_LAST_SEEN_UPDATE.format(device_id=device_id))

    def _notify_stats_changed(self):
        async_dispatcher_send(self.hass, SIGNAL_HUB_STATS_UPDATE)

    async def _resync(self):
        fresh_store = Store(self.hass, 1, f"{DOMAIN}_{self.entry.entry_id}")
        stored = await fresh_store.async_load()
        if stored is not None:
            self.pairing_key = stored.get("pairing_key", self.pairing_key)
            self.device_keys = dict(stored.get("device_keys", self.device_keys))
            self.pending_devices = dict(stored.get("pending_devices", self.pending_devices))
            self.thresholds = dict(stored.get("thresholds", self.thresholds))
            self.online_timeout = max(10, min(86400, int(stored.get("online_timeout", self.online_timeout))))
            self.last_seen_enabled = bool(stored.get("last_seen_enabled", self.last_seen_enabled))
            self.online_sensors_enabled = bool(stored.get("online_sensors_enabled", self.online_sensors_enabled))
            self.last_seen_update_interval = max(1, min(3600, int(stored.get("last_seen_update_interval", self.last_seen_update_interval))))

    async def _persist(self):
        data = {
            "pairing_key": self.pairing_key,
            "device_keys": self.device_keys,
            "pending_devices": self.pending_devices,
            "thresholds": self.thresholds,
            "online_timeout": self.online_timeout,
            "online_timeout_is_seconds": True,
            "last_seen_enabled": self.last_seen_enabled,
            "online_sensors_enabled": self.online_sensors_enabled,
            "last_seen_update_interval": self.last_seen_update_interval,
        }
        await self._store.async_save(data)


    async def async_device_connected(self, device_id, hello):
        model = hello.get("model")
        sw_version = hello.get("sw_version")
        self.devices.setdefault(device_id, {})
        self.devices[device_id]["sw_version"] = sw_version
        self.devices[device_id]["model"] = model

        dev_reg = dr.async_get(self.hass)
        hub_device = dev_reg.async_get_device_by_identifier((DOMAIN, HUB_IDENTIFIER), self.entry.entry_id)
        dev_reg.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, device_id)},
            name=device_id,
            manufacturer="Henrik Isefjær Olsen",
            model=model,
            sw_version=sw_version,
            via_device_id=hub_device.id if hub_device else None,
        )
        _LOGGER.info("TuxD device connected: %s", device_id)
        self._touch_last_seen(device_id)

        self._device_generation[device_id] = self._device_generation.get(device_id, 0) + 1
        self.hass.async_create_task(
            self._reconcile_device_entities(device_id, self._device_generation[device_id])
        )

        self._notify_stats_changed()

    async def _reconcile_device_entities(self, device_id, generation):
        await asyncio.sleep(self._RECONCILE_SETTLE_SECONDS)
        if self._device_generation.get(device_id) != generation:
            return

        stale = [
            (uid, e.get("domain")) for uid, e in self.entities.items()
            if e.get("device_id") == device_id and e.get("_generation") != generation
        ]
        for uid, domain in stale:
            self.entities.pop(uid, None)
            if domain:
                async_dispatcher_send(self.hass, SIGNAL_REMOVE_ENTITY.format(domain=domain), uid)
        for uids in self.key_to_unique_ids.values():
            uids.difference_update(uid for uid, _domain in stale)
        removed = len(stale)

        dev_reg = dr.async_get(self.hass)
        device_entry = dev_reg.async_get_device_by_identifier((DOMAIN, device_id), self.entry.entry_id)
        if device_entry is not None:
            ent_reg = er.async_get(self.hass)
            confirmed = {
                uid for uid, e in self.entities.items()
                if e.get("device_id") == device_id and e.get("_generation") == generation
            }
            for reg_entry in list(er.async_entries_for_device(ent_reg, device_entry.id, include_disabled_entities=True)):
                if reg_entry.unique_id not in confirmed:
                    ent_reg.async_remove(reg_entry.entity_id)
                    removed += 1

        if removed:
            _LOGGER.info(
                "TuxD: device %s no longer announces %d entit%s - removed",
                device_id, removed, "y" if removed == 1 else "ies",
            )
            self._notify_stats_changed()

    def async_set_ws(self, device_id, ws):
        info = self.devices.setdefault(device_id, {})
        old_ws = info.get("ws")
        info["ws"] = ws
        if old_ws is not None and old_ws is not ws:
            self.hass.async_create_task(old_ws.close())

    def async_device_disconnected(self, device_id, ws=None):
        current = self.devices.get(device_id, {}).get("ws")
        if ws is not None and current is not None and current is not ws:
            return
        self.devices.pop(device_id, None)
        for request_id, request in list(self._config_requests.items()):
            if request["device_id"] == device_id:
                self._config_requests.pop(request_id, None)
                if not request["future"].done():
                    request["future"].set_result({"ok": False, "error": "Device disconnected"})
        _LOGGER.info("TuxD device disconnected: %s", device_id)
        for uid, entry in self.entities.items():
            if entry.get("device_id") == device_id:
                async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE.format(unique_id=uid))
        self._notify_stats_changed()

        for session_id, info in list(self._tty_sessions.items()):
            if info["device_id"] == device_id:
                self._tty_sessions.pop(session_id, None)
                info["connection"].send_message(
                    websocket_api.event_message(info["msg_id"], {"type": "tty_exit", "code": -1})
                )


    def tty_open(self, device_id, connection, msg_id, cols, rows, password=None):
        info = self.devices.get(device_id)
        if not info or "ws" not in info:
            return None
        session_id = uuid.uuid4().hex[:12]
        self._tty_sessions[session_id] = {
            "device_id": device_id, "connection": connection, "msg_id": msg_id,
        }
        ws = info["ws"]
        payload = {"type": "tty_open", "session": session_id, "cols": cols, "rows": rows}
        if password is not None:
            payload["password"] = password
        asyncio.create_task(ws.send_str(json.dumps(payload)))
        return session_id

    def tty_input(self, session_id, data):
        self._tty_send(session_id, {"type": "tty_input", "session": session_id, "data": data})

    def tty_resize(self, session_id, cols, rows):
        self._tty_send(session_id, {"type": "tty_resize", "session": session_id, "cols": cols, "rows": rows})

    def tty_close(self, session_id):
        self._tty_send(session_id, {"type": "tty_close", "session": session_id})
        self._tty_sessions.pop(session_id, None)

    def _tty_send(self, session_id, obj):
        info = self._tty_sessions.get(session_id)
        if not info:
            return
        dev = self.devices.get(info["device_id"])
        if not dev or "ws" not in dev:
            return
        asyncio.create_task(dev["ws"].send_str(json.dumps(obj)))

    def _handle_tty_data(self, device_id, msg):
        session_id = msg.get("session")
        info = self._tty_sessions.get(session_id)
        if not info or info["device_id"] != device_id:
            return
        info["connection"].send_message(
            websocket_api.event_message(info["msg_id"], {"type": "tty_data", "data": msg.get("data", "")})
        )

    def _handle_tty_exit(self, device_id, msg):
        session_id = msg.get("session")
        info = self._tty_sessions.pop(session_id, None)
        if not info or info["device_id"] != device_id:
            return
        event = {"type": "tty_exit", "code": msg.get("code", -1)}
        if msg.get("reason"):
            event["reason"] = msg["reason"]
        info["connection"].send_message(
            websocket_api.event_message(info["msg_id"], event)
        )

    async def run_terminal_command(self, device_id, cmd, password=None, wait_seconds=6.0):
        if device_id not in self.devices or "ws" not in self.devices[device_id]:
            return {"ok": False, "output": "", "error": "Device is not connected"}
        collector = _HeadlessTtyCollector()
        session_id = self.tty_open(device_id, collector, f"cfgflow-{device_id}", 200, 50, password or None)
        if session_id is None:
            return {"ok": False, "output": "", "error": "Device is not connected"}
        exited_early = False
        try:
            data_b64 = base64.b64encode((cmd + "\r").encode("utf-8")).decode("ascii")
            self.tty_input(session_id, data_b64)
            try:
                await asyncio.wait_for(collector.exit_event.wait(), timeout=wait_seconds)
                exited_early = True
            except asyncio.TimeoutError:
                pass
        finally:
            self.tty_close(session_id)
        output = _strip_ansi("".join(collector.output))
        if collector.exit_code == -2:
            return {"ok": False, "output": output, "error": collector.exit_reason or "Password required"}
        if exited_early and not output.strip():
            return {"ok": False, "output": output, "error": collector.exit_reason or "Terminal session ended unexpectedly (busy or disabled)"}
        return {"ok": True, "output": output, "error": None}

    def terminal_enabled_devices(self):
        return sorted({
            entry.get("device_id")
            for entry in self.entities.values()
            if entry.get("domain") == "text"
            and entry.get("object_id") == "terminal_input"
            and entry.get("device_id") in self.devices
        })


    async def async_handle_message(self, device_id, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        self._touch_last_seen(device_id)

        mtype = msg.get("type")
        if mtype == "discovery":
            self._handle_discovery(device_id, msg)
        elif mtype == "discovery_clear":
            self._handle_discovery_clear(device_id, msg)
        elif mtype == "state":
            self._handle_state(device_id, msg)
        elif mtype == "tty_data":
            self._handle_tty_data(device_id, msg)
        elif mtype == "tty_exit":
            self._handle_tty_exit(device_id, msg)
        elif mtype == "config_response":
            request = self._config_requests.get(msg.get("request_id"))
            if request and request["device_id"] == device_id and not request["future"].done():
                request["future"].set_result(msg)
        elif mtype == "ping":
            ws = self.devices.get(device_id, {}).get("ws")
            if ws is not None:
                await ws.send_str(json.dumps({"type": "pong"}))

    def _owns_key(self, device_id, key):
        return key == f"tuxd/{device_id}" or key.startswith(f"tuxd/{device_id}/")

    def _handle_discovery(self, device_id, msg):
        domain = msg.get("domain")
        object_id = msg.get("object_id")
        config = msg.get("config") or {}
        if not domain or not object_id:
            return
        if domain not in PLATFORMS:
            _LOGGER.warning(
                "TuxD: device %s tried to register unsupported domain %s - ignored",
                device_id, domain,
            )
            return
        unique_id = config.get("unique_id") or f"{device_id}_{object_id}"
        if unique_id != device_id and not unique_id.startswith(f"{device_id}_"):
            _LOGGER.warning(
                "TuxD: device %s tried to register entity %s outside its own namespace - ignored",
                device_id, unique_id,
            )
            return

        state_topic = config.get("state_topic") or config.get("stat_t")
        attrs_topic = config.get("json_attributes_topic")
        for topic in (state_topic, attrs_topic):
            if topic and not self._owns_key(device_id, topic):
                _LOGGER.warning(
                    "TuxD: device %s tried to register topic %s outside its own namespace - ignored",
                    device_id, topic,
                )
                return

        existing = self.entities.get(unique_id)
        if existing is not None and existing.get("device_id") not in (None, device_id):
            _LOGGER.warning(
                "TuxD: device %s tried to claim entity %s already owned by %s - ignored",
                device_id, unique_id, existing.get("device_id"),
            )
            return

        is_new = existing is None
        entry = self.entities.setdefault(unique_id, {"state": None, "attributes": {}})
        entry["domain"] = domain
        entry["object_id"] = object_id
        entry["device_id"] = device_id
        entry["config"] = config
        entry["_generation"] = self._device_generation.get(device_id, 0)

        if state_topic:
            self.key_to_unique_ids.setdefault(state_topic, set()).add(unique_id)
        if attrs_topic:
            self.key_to_unique_ids.setdefault(attrs_topic, set()).add(unique_id)

        self._migrate_enabled_entity_id(domain, object_id, unique_id, config)

        if is_new:
            async_dispatcher_send(self.hass, SIGNAL_NEW_ENTITY.format(domain=domain), unique_id)
        else:
            async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE.format(unique_id=unique_id))
        if _is_stats_relevant_object_id(object_id):
            self._notify_stats_changed()

    def _migrate_enabled_entity_id(self, domain, object_id, unique_id, config):
        if domain != "binary_sensor" or object_id not in ("docker_enabled", "tugboat_enabled"):
            return
        wanted = config.get("default_entity_id") or ""
        legacy = wanted.replace(f"_{object_id}", "_enabled")
        if not wanted.endswith(f"_{object_id}") or legacy == wanted:
            return
        ent_reg = er.async_get(self.hass)
        current = ent_reg.async_get_entity_id(domain, DOMAIN, unique_id)
        if not current or current == wanted:
            return
        if not re.fullmatch(re.escape(legacy) + r"(_\d+)?", current):
            return
        if ent_reg.async_get(wanted) is not None:
            return
        try:
            ent_reg.async_update_entity(current, new_entity_id=wanted)
            _LOGGER.info("TuxD: renamed %s to %s", current, wanted)
        except ValueError:
            pass

    def _handle_discovery_clear(self, device_id, msg):
        domain = msg.get("domain")
        object_id = msg.get("object_id")
        stale = [
            uid for uid, e in self.entities.items()
            if e.get("domain") == domain and e.get("object_id") == object_id
            and e.get("device_id") == device_id
        ]
        for uid in stale:
            self.entities.pop(uid, None)
            async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE.format(unique_id=uid))
            async_dispatcher_send(self.hass, SIGNAL_REMOVE_ENTITY.format(domain=domain), uid)
        for uids in self.key_to_unique_ids.values():
            uids.difference_update(stale)
        if _is_stats_relevant_object_id(object_id):
            self._notify_stats_changed()

    def _handle_state(self, device_id, msg):
        key = msg.get("key")
        value = msg.get("value")
        if not key or not self._owns_key(device_id, key):
            _LOGGER.warning(
                "TuxD: device %s tried to publish state for %s outside its own namespace - ignored",
                device_id, key,
            )
            return
        for uid in self.key_to_unique_ids.get(key, ()):
            entry = self.entities.get(uid)
            if not entry or entry.get("device_id") != device_id:
                continue
            cfg = entry.get("config", {})
            if cfg.get("json_attributes_topic") == key:
                try:
                    entry["attributes"] = json.loads(value)
                except Exception:
                    pass
            else:
                entry["state"] = value
            async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATE.format(unique_id=uid))
            if _is_stats_relevant_object_id(entry.get("object_id") or ""):
                self._notify_stats_changed()


    async def async_get_device_config(self, device_id):
        return await self._async_config_request(device_id, "get")

    async def async_set_device_config(self, device_id, content):
        return await self._async_config_request(device_id, "set", content)

    def _resolve_device_id(self, device_id):
        if device_id in self.devices:
            return device_id
        normalized = re.sub(r"[-_]+", "_", str(device_id or "")).lower()
        for real_id in self.devices:
            if re.sub(r"[-_]+", "_", real_id).lower() == normalized:
                return real_id
        return None

    async def _async_config_request(self, device_id, action, content=None):
        resolved = self._resolve_device_id(device_id)
        if resolved is None or "ws" not in self.devices[resolved]:
            return {"ok": False, "error": "Device is not connected"}
        device_id = resolved
        request_id = uuid.uuid4().hex
        future = self.hass.loop.create_future()
        self._config_requests[request_id] = {"device_id": device_id, "future": future}
        payload = {"request_id": request_id, "action": action}
        if content is not None:
            payload["content"] = content
        self.send_command(device_id, f"tuxd/{device_id}/config/{action}", json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=10)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Timed out waiting for the device"}
        finally:
            self._config_requests.pop(request_id, None)

    def send_command(self, device_id, key, payload):
        info = self.devices.get(device_id)
        if not info or "ws" not in info:
            _LOGGER.warning("TuxD: cannot send command, %s is not connected", device_id)
            return
        ws = info["ws"]
        asyncio.create_task(ws.send_str(json.dumps({"type": "command", "key": key, "payload": payload})))

    _FLEET_COMMAND_STAGGER_SECONDS = 2.0

    async def _send_staggered(self, topic_suffix, payload="PRESS"):
        for device_id in list(self.devices.keys()):
            self.send_command(device_id, f"tuxd/{device_id}/{topic_suffix}/set", payload)
            await asyncio.sleep(self._FLEET_COMMAND_STAGGER_SECONDS)

    def restart_all_devices(self):
        self.hass.async_create_task(self._send_staggered("restart"))

    def refresh_all_devices(self):
        self.hass.async_create_task(self._send_staggered("force_poll"))

    def set_offline_update_url(self, url):
        self.offline_update_url = (url or "").strip()
        async_dispatcher_send(self.hass, SIGNAL_OFFLINE_UPDATE_URL_CHANGED)

    def update_all_devices(self):
        if self.offline_update_url:
            self.hass.async_create_task(
                self._send_staggered("self_update/install_from_url", payload=self.offline_update_url)
            )
        else:
            self.hass.async_create_task(self._send_staggered("self_update"))

    def check_host_updates_all_devices(self):
        self.hass.async_create_task(self._send_staggered("host_update/check"))

    def restore_entity_ids(self):
        ent_reg = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(ent_reg, self.entry.entry_id)

        renamed = 0
        skipped = 0
        reserved_entity_ids = set()
        for reg_entry in entries:
            new_entity_id = ent_reg.async_regenerate_entity_id(
                reg_entry, reserved_entity_ids=reserved_entity_ids
            )
            reserved_entity_ids.add(new_entity_id)
            if new_entity_id == reg_entry.entity_id:
                continue
            try:
                ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=new_entity_id)
                renamed += 1
            except ValueError:
                skipped += 1

        return renamed, skipped

    async def set_threshold(self, key, value):
        self.thresholds[key] = value
        await self._persist()
        async_dispatcher_send(self.hass, SIGNAL_THRESHOLDS_CHANGED)

    async def set_online_timeout(self, value):
        self.online_timeout = max(10, min(86400, int(value)))
        await self._persist()
        async_dispatcher_send(self.hass, SIGNAL_ONLINE_TIMEOUT_CHANGED)

    async def set_last_seen_update_interval(self, value):
        self.last_seen_update_interval = max(1, min(3600, int(value)))
        await self._persist()
        async_dispatcher_send(self.hass, SIGNAL_LAST_SEEN_UPDATE_INTERVAL_CHANGED)

    async def set_last_seen_enabled(self, enabled):
        self.last_seen_enabled = bool(enabled)
        await self._persist()
        async_dispatcher_send(self.hass, SIGNAL_LAST_SEEN_ENABLED_CHANGED)

    async def set_online_sensors_enabled(self, enabled):
        self.online_sensors_enabled = bool(enabled)
        await self._persist()
        async_dispatcher_send(self.hass, SIGNAL_ONLINE_SENSORS_ENABLED_CHANGED)
