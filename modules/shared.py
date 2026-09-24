import re
import subprocess


def slugify(s):
    # Shared slug rule for anything that ends up in an entity_id: lowercase,
    # non-alphanumerics collapsed to a single underscore, trimmed. Kept
    # byte-for-byte identical to TuxD (Linux agent)'s shared.py on purpose -
    # this is what makes "identical entity id format" between the two
    # agents possible at all, since both feed the exact same TuxD-HA
    # integration and Lovelace cards.
    s = re.sub(r"[^a-z0-9]+", "_", str(s).lower())
    return s.strip("_")


_ENTITY_COMPONENT_PREFIXES = (
    "builtin_", "custom_button_", "custom_sensor_", "disk_", "docker_",
    "lag_monitor_", "log_sensor_", "net_", "select_",
    "self_update_", "status_", "system_",
)


def entity_object_id(object_id):
    object_id = str(object_id)
    for prefix in _ENTITY_COMPONENT_PREFIXES:
        if object_id.startswith(prefix):
            object_id = object_id[len(prefix):]
            break
    return re.sub(
        r"_(?:bytes?|gb|kb|mb|mbps|pct|percent|ms|seconds?|minutes?|hours?)$",
        "",
        object_id,
    )


def run_cmd(cmd: str, env=None):
    if not cmd or cmd.strip() == "":
        return ""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            env=env
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERR: {e}"


def run_powershell(script: str, timeout=30):
    # Windows-only helper (TuxD's shared.py has no equivalent - nothing on
    # Linux needs it) - every Windows-specific check that isn't cleanly
    # available via psutil (Windows Update, service recovery info, ...)
    # shells out to a single -Command invocation rather than a temp .ps1
    # file, so nothing is ever left behind on disk. -NoProfile/-NonInteractive
    # avoid a slow profile-script load and any chance of a hung prompt.
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERR: {e}"
