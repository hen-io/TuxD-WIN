import os
import json
import re
import tempfile
import time
import yaml

from .password import is_password_hash, verify_password

_CONFIG_FILE = "tuxd-win.conf"


class ConfigAgentMixin:

    def password_check(self, given):
        stored = str((self.config.get("device", {}) or {}).get("password_hash") or "")
        if not stored:
            return None
        if not given:
            return "required"
        if verify_password(given, stored):
            return None
        time.sleep(1.0)
        return "incorrect"

    def handle_config_request(self, payload):
        try:
            request = json.loads(payload or "{}")
            request_id = str(request.get("request_id") or "")
            action = request.get("action")
            if not request_id or action not in ("get", "set", "set_password"):
                return

            denied = self.password_check(request.get("password"))
            if denied:
                self._send_config_response(
                    request_id, False, auth=denied,
                    error="Incorrect password" if denied == "incorrect" else "Password required",
                )
                return

            if action == "set_password":
                self._set_password_hash(str(request.get("content") or ""))
                self._send_config_response(request_id, True)
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

            device = parsed.get("device") if isinstance(parsed.get("device"), dict) else {}
            ha = parsed.get("home-assistant") if isinstance(parsed.get("home-assistant"), dict) else {}
            if not str(device.get("name") or "").strip():
                self._send_config_response(request_id, False, error="device.name must be set")
                return
            if not str(ha.get("url") or "").strip():
                self._send_config_response(request_id, False, error="home-assistant.url must be set")
                return

            if os.path.exists(_CONFIG_FILE):
                with open(_CONFIG_FILE, "r", encoding="utf-8") as src, open(_CONFIG_FILE + ".bak", "w", encoding="utf-8", newline="") as dst:
                    dst.write(src.read())

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

    def _set_password_hash(self, password_hash):
        if password_hash and not is_password_hash(password_hash):
            raise ValueError("Not a password hash")
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            text = f.read()
        line = f'  password_hash: "{password_hash}"'
        if re.search(r"^  password_hash:.*$", text, flags=re.M):
            text = re.sub(r"^  password_hash:.*$", lambda _m: line, text, count=1, flags=re.M)
        else:
            text = re.sub(r"^device:[ \t]*$", lambda m: m.group(0) + "\n" + line, text, count=1, flags=re.M)
        with open(_CONFIG_FILE, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self._config_own_write_mtime = os.path.getmtime(_CONFIG_FILE)
        self.config.setdefault("device", {})["password_hash"] = password_hash

    def _send_config_response(self, request_id, ok, content=None, error=None, auth=None):
        sender = getattr(self, "_send_wait", None)
        if not callable(sender):
            return
        message = {"type": "config_response", "request_id": request_id, "ok": bool(ok)}
        if content is not None:
            message["content"] = content
        if error:
            message["error"] = error[:500]
        if auth:
            message["auth"] = auth
        sender(message, timeout=5.0)

    def config_file_watch_loop(self):
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
                if current != getattr(self, "_config_own_write_mtime", None):
                    self._hard_restart()
