import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.2.1"
GITHUB_REPO = "hen-io/TuxD-WIN"
CONFIG_FILE = "tuxd-win.conf"


def _selftest():
    import getpass
    import importlib

    here = Path(__file__).resolve().parent
    lines = [
        f"python: {sys.executable} ({sys.version.split()[0]})",
        f"user: {getpass.getuser()}",
        f"cwd: {os.getcwd()}",
    ]
    ok = True
    for name in ("websockets", "yaml", "psutil"):
        try:
            mod = importlib.import_module(name)
            lines.append(f"import {name}: ok ({getattr(mod, '__version__', '?')})")
        except Exception as e:
            ok = False
            lines.append(f"import {name}: FAILED ({e!r})")

    lines.append(f"{CONFIG_FILE}: {'found' if (here / CONFIG_FILE).exists() else 'not found yet'}")
    lines.append("SELFTEST_OK" if ok else "SELFTEST_FAILED")
    text = "\n".join(lines) + "\n"
    print(text)
    try:
        (here / "selftest.log").write_text(text, encoding="utf-8")
    except Exception as e:
        print(f"could not write selftest.log next to windows_start.py: {e!r}")
        return 1
    return 0 if ok else 1


if __name__ == "__main__" and "--selftest" in sys.argv:
    sys.exit(_selftest())



_FAST_EXIT_SECONDS = 5.0
_RESTART_DELAY = 2.0
_MAX_BACKOFF = 30.0
_SUPERVISOR_PID_ARG = "--supervisor-pid="


def _child_command():
    return [sys.executable, str(Path(__file__).resolve()), "--child", f"{_SUPERVISOR_PID_ARG}{os.getpid()}"]


def _supervise():
    print(f"TuxD-Win supervisor {VERSION}: started (pid {os.getpid()})", flush=True)
    fast_exits = 0
    child = None
    try:
        while True:
            started = time.monotonic()
            code = "not started"
            try:
                child = subprocess.Popen(_child_command())
                while True:
                    try:
                        code = child.wait(timeout=1.0)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            except OSError as e:
                code = repr(e)
            child = None

            ran = time.monotonic() - started
            if ran < _FAST_EXIT_SECONDS:
                fast_exits = min(fast_exits + 1, 10)
                delay = min(_MAX_BACKOFF, 5.0 * 2 ** (fast_exits - 1))
            else:
                fast_exits = 0
                delay = _RESTART_DELAY
            print(f"TuxD-Win supervisor: agent exited ({code}) after {ran:.0f}s, restarting in {delay:.0f}s", flush=True)
            time.sleep(delay)
    except KeyboardInterrupt:
        if child is not None:
            try:
                child.wait(timeout=10)
            except Exception:
                child.terminate()
        return 0


if __name__ == "__main__" and "--child" not in sys.argv:
    sys.exit(_supervise())

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.base_direct import HADirectBase
from modules.restart import RestartMixin
from modules.config_agent import ConfigAgentMixin
from modules.self_update_agent import SelfUpdateMixin
from modules.system_agent import SystemMetricsMixin
from modules.network_agent import NetworkMixin
from modules.disks_agent import DisksMixin
from modules.services_agent import ServicesMixin
from modules.host_update_agent import HostUpdateMixin
from modules.shared import entity_object_id


class TuxDWinAgent(
    RestartMixin,
    ConfigAgentMixin,
    SelfUpdateMixin,
    SystemMetricsMixin,
    NetworkMixin,
    DisksMixin,
    ServicesMixin,
    HostUpdateMixin,
    HADirectBase,
):
    def __init__(self, config, version, update_checker=None, update_applier=None):
        super().__init__(config, version)
        self._update_checker = update_checker
        self._update_applier = update_applier
        self.init_system_metrics()
        self.init_network()
        self.init_disks()
        self.init_services()
        self.init_host_update()
        self.init_self_update()


    def _sensor_discovery(self, object_id, name, state_topic, unit=None, icon=None, attributes_topic=None, ha_object_id=None, state_class=None, entity_category=None, device_class=None):
        payload = {
            "name": name,
            "state_topic": state_topic,
            "unique_id": f"{self.config['device']['name']}_{object_id}",
            "device": self.device_info,
        }
        entity_id = ha_object_id or f"{self.device_slug}_{entity_object_id(object_id)}"
        payload["default_entity_id"] = f"sensor.{entity_id}"
        if state_class:
            payload["state_class"] = state_class
        if unit:
            payload["unit_of_measurement"] = unit
        if icon:
            payload["icon"] = icon
        if attributes_topic:
            payload["json_attributes_topic"] = attributes_topic
        if entity_category:
            payload["entity_category"] = entity_category
        if device_class:
            payload["device_class"] = device_class
        self.publish(self._discovery_topic("sensor", object_id), json.dumps(payload), retain=True)

    def _binary_sensor_discovery(self, object_id, name, state_topic, device_class=None, icon=None, attributes_topic=None, entity_category=None):
        payload = {
            "name": name,
            "state_topic": state_topic,
            "unique_id": f"{self.config['device']['name']}_{object_id}",
            "device": self.device_info,
            "payload_on": "ON",
            "payload_off": "OFF",
        }
        payload["default_entity_id"] = f"binary_sensor.{self.device_slug}_{entity_object_id(object_id)}"
        if device_class:
            payload["device_class"] = device_class
        if icon:
            payload["icon"] = icon
        if attributes_topic:
            payload["json_attributes_topic"] = attributes_topic
        if entity_category:
            payload["entity_category"] = entity_category
        self.publish(self._discovery_topic("binary_sensor", object_id), json.dumps(payload), retain=True)

    def _update_discovery(self, object_id, name, state_topic, command_topic=None, device_class=None, icon=None, entity_category=None, ha_object_id=None, payload_install="INSTALL"):
        payload = {
            "name": name,
            "state_topic": state_topic,
            "unique_id": f"{self.config['device']['name']}_{object_id}",
            "device": self.device_info,
        }
        if command_topic:
            payload["command_topic"] = command_topic
            payload["payload_install"] = payload_install
        if device_class:
            payload["device_class"] = device_class
        if icon:
            payload["icon"] = icon
        if entity_category:
            payload["entity_category"] = entity_category
        entity_id = ha_object_id or f"{self.device_slug}_{entity_object_id(object_id)}"
        payload["default_entity_id"] = f"update.{entity_id}"
        self.publish(self._discovery_topic("update", object_id), json.dumps(payload), retain=True)

    def _button_discovery(self, object_id, name, command_topic, icon=None, entity_category=None):
        payload = {
            "name": name,
            "command_topic": command_topic,
            "unique_id": f"{self.config['device']['name']}_{object_id}",
            "device": self.device_info,
            "default_entity_id": f"button.{self.device_slug}_{entity_object_id(object_id)}",
        }
        if icon:
            payload["icon"] = icon
        if entity_category:
            payload["entity_category"] = entity_category
        self.publish(self._discovery_topic("button", object_id), json.dumps(payload), retain=True)


    def refresh_discovery(self):
        registrars = (
            self.register_restart_button,
            self.register_system_metrics,
            self.register_network,
            self.register_disks,
            self.register_services,
            self.register_host_update,
            self.register_self_update,
        )
        for registrar in registrars:
            try:
                registrar()
            except Exception as e:
                print(f"TuxD-Win: {registrar.__name__} failed: {e!r}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode()

        if topic == f"{self.base_topic}/restart/set":
            self.handle_restart_message()
        elif topic == f"{self.base_topic}/force_poll/set":
            self.handle_force_poll_message()
        elif topic == f"{self.base_topic}/host_update/check/set":
            self.handle_host_update_check()
        elif topic == f"{self.base_topic}/self_update/set":
            self.handle_self_update_install()
        elif topic == f"{self.base_topic}/self_update/check/set":
            self.handle_self_update_check()
        elif topic == f"{self.base_topic}/self_update/install_from_url/set":
            self.handle_self_update_install_from_url(payload)
        elif topic == f"{self.base_topic}/config/get" or topic == f"{self.base_topic}/config/set":
            self.handle_config_request(payload)

    def start(self):
        self.connect()
        threading.Thread(target=self.system_metrics_loop, daemon=True).start()
        threading.Thread(target=self.network_loop, daemon=True).start()
        threading.Thread(target=self.disks_loop, daemon=True).start()
        threading.Thread(target=self.services_loop, daemon=True).start()
        threading.Thread(target=self.host_update_loop, daemon=True).start()
        threading.Thread(target=self.self_update_loop, daemon=True).start()
        threading.Thread(target=self.config_file_watch_loop, daemon=True).start()
        print(f"TuxD-Win {self.version}: startup complete, connected as {self.config['device']['name']}")
        try:
            self._stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self._stop_event.set()



def _github_headers():
    headers = {"User-Agent": "TuxD-Win-Updater"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        try:
            token = (Path(__file__).resolve().parent / "github.token").read_text(encoding="utf-8").strip()
        except Exception:
            token = ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_newer(tag, current):
    try:
        return tuple(int(p) for p in tag.split(".")) > tuple(int(p) for p in current.split("."))
    except ValueError:
        return tag != current


def check_for_update(force=False):
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers=_github_headers(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"TuxD-Win: update check failed: {e!r}")
        return None, None, None, None

    tag = str(release.get("tag_name") or "").lstrip("v")
    if not tag or not _is_newer(tag, VERSION):
        return None, None, None, None

    download_url = ""
    for asset in release.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.endswith(".zip") or name.endswith(".tar.gz"):
            download_url = str(asset.get("browser_download_url", "")).strip()
            break
    if not download_url:
        download_url = str(release.get("zipball_url") or release.get("tarball_url") or "").strip()
    if not download_url:
        return None, None, None, None

    notes = (release.get("body") or "")[:500]
    return tag, "url", download_url, notes


def _safe_extract(archive_path: Path, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as z:
            dest_real = os.path.realpath(dest_dir)
            for member in z.infolist():
                target = os.path.realpath(os.path.join(dest_real, member.filename))
                if target != dest_real and not target.startswith(dest_real + os.sep):
                    raise RuntimeError(f"Unsafe path in update archive: {member.filename}")
            z.extractall(dest_dir)
        return
    with tarfile.open(archive_path, "r:gz") as t:
        try:
            t.extractall(dest_dir, filter="data")
        except TypeError:
            dest_real = os.path.realpath(dest_dir)
            safe_members = []
            for member in t.getmembers():
                if member.issym() or member.islnk():
                    continue
                target = os.path.realpath(os.path.join(dest_real, member.name))
                if target != dest_real and not target.startswith(dest_real + os.sep):
                    raise RuntimeError(f"Unsafe path in update archive: {member.name}")
                safe_members.append(member)
            t.extractall(dest_dir, members=safe_members)


def _find_release_root(extracted_dir: Path):
    if (extracted_dir / "windows_start.py").exists():
        return extracted_dir
    kids = [p for p in extracted_dir.iterdir() if p.is_dir()]
    if len(kids) == 1:
        return kids[0]
    return extracted_dir


def apply_update(new_version, source_type, source_value):
    install_dir = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        archive_path = td_path / "release.archive"
        req = urllib.request.Request(source_value, headers=_github_headers())
        with urllib.request.urlopen(req, timeout=60) as resp, open(archive_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        extract_dir = td_path / "extract"
        _safe_extract(archive_path, extract_dir)
        release_root = _find_release_root(extract_dir)
        if not (release_root / "windows_start.py").exists():
            raise RuntimeError("Downloaded release doesn't look like a valid TuxD-Win build")

        saved_conf = None
        conf_path = install_dir / CONFIG_FILE
        if conf_path.exists():
            saved_conf = conf_path.read_bytes()

        for item in release_root.iterdir():
            dest = install_dir / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))

        if saved_conf is not None:
            conf_path.write_bytes(saved_conf)

    print(f"TuxD-Win: updated to {new_version}, exiting for the supervisor to restart into the new version...")
    time.sleep(1.0)
    os._exit(1)



def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise SystemExit(
            f"TuxD-Win: {CONFIG_FILE} not found in the current directory - copy tuxd-win.conf.example "
            "next to windows_start.py, fill in device.name and home-assistant.url/pairing_key, then retry."
        )
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _watch_supervisor(pid, interval=5.0):
    import psutil

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        os._exit(0)
    except Exception:
        return

    def loop():
        while True:
            time.sleep(interval)
            try:
                alive = parent.is_running()
            except Exception:
                continue
            if not alive:
                print("TuxD-Win: supervisor is gone, exiting", flush=True)
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


def main():
    for arg in sys.argv[1:]:
        if arg.startswith(_SUPERVISOR_PID_ARG):
            try:
                _watch_supervisor(int(arg[len(_SUPERVISOR_PID_ARG):]))
            except ValueError:
                pass

    config = load_config()
    if not (config.get("device") or {}).get("name"):
        raise SystemExit("TuxD-Win: device.name must be set in tuxd-win.conf")

    agent = TuxDWinAgent(
        config,
        VERSION,
        update_checker=check_for_update,
        update_applier=apply_update,
    )
    agent.start()


if __name__ == "__main__":
    main()
