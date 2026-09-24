import os
import json
import tempfile
import yaml

_CONFIG_FILE = "tuxd-win.conf"


class ConfigAgentMixin:
    """Vendored from TuxD (Linux agent)'s config_agent.py, trimmed to just
    the raw get/set-whole-file request handling (the config/get, config/set
    topics TuxD-HA's hub.py/config_editor.py/config_flow.py already speak) -
    TuxD-Win is "lite" enough that it skips the per-field cfgnum/cfgsw/cfgtxt
    config entities and the shared extra_config_path fleet-config merge
    Linux devices support. Editing tuxd-win.conf through Home Assistant's
    existing "Edit device configuration" screen works unmodified regardless -
    that feature only ever calls this same get/set protocol, one whole file
    at a time, and doesn't care what platform is on the other end of it.
    """

    def handle_config_request(self, payload):
        try:
            request = json.loads(payload or "{}")
            request_id = str(request.get("request_id") or "")
            action = request.get("action")
            if not request_id or action not in ("get", "set"):
                return

            if action == "get":
                with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                self._send_config_response(request_id, True, content=content)
                return

            content = request.get("content")
            if not isinstance(content, str) or len(content) > 1024 * 1024:
                self._send_config_response(request_id, False, error="Configuration is missing or too large")
                return
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                self._send_config_response(request_id, False, error="tuxd-win.conf must contain a YAML mapping")
                return

            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=".", prefix=".tuxd-win.conf.", delete=False
            ) as tmp:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_path = tmp.name
            os.replace(temp_path, _CONFIG_FILE)
            self._send_config_response(request_id, True)
        except Exception as e:
            try:
                if "temp_path" in locals():
                    os.unlink(temp_path)
            except Exception:
                pass
            self._send_config_response(request_id, False, error=str(e))

    def _send_config_response(self, request_id, ok, content=None, error=None):
        sender = getattr(self, "_send_wait", None)
        if not callable(sender):
            return
        message = {"type": "config_response", "request_id": request_id, "ok": bool(ok)}
        if content is not None:
            message["content"] = content
        if error:
            message["error"] = error[:500]
        sender(message, timeout=5.0)

    def config_file_watch_loop(self):
        # Same reasoning as TuxD's own config_file_watch_loop (fixed earlier
        # this project for missing a second watched file) - simpler here
        # since there's only ever the one file to watch.
        def _mtime():
            try:
                return os.path.getmtime(_CONFIG_FILE)
            except OSError:
                return None

        last = _mtime()
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=2.0)
            if self._stop_event.is_set():
                return
            current = _mtime()
            if current is not None and current != last:
                last = current
                self._hard_restart()
