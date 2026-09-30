import json
import subprocess
import threading

from .shared import run_powershell

_UPDATE_CHECK_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "try { "
    "$s = New-Object -ComObject Microsoft.Update.Session; "
    "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); "
    "Write-Output $r.Updates.Count; "
    "foreach ($u in $r.Updates) { Write-Output ($u.Title -replace '[^\\x20-\\x7E]', '?') } "
    "} catch { Write-Output '-1' }"
)

_MAX_LISTED_UPDATES = 50

_UPDATE_INSTALL_SCRIPT = "\n".join([
    "$ErrorActionPreference = 'Stop'",
    "try {",
    "  $s = New-Object -ComObject Microsoft.Update.Session",
    "  $r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0')",
    "  if ($r.Updates.Count -eq 0) { Write-Output 'RESULT:2'; Write-Output 'REBOOT:False'; exit 0 }",
    "  $c = New-Object -ComObject Microsoft.Update.UpdateColl",
    "  foreach ($u in $r.Updates) { if (-not $u.EulaAccepted) { $u.AcceptEula() }; [void]$c.Add($u) }",
    "  $d = $s.CreateUpdateDownloader(); $d.Updates = $c; [void]$d.Download()",
    "  $i = $s.CreateUpdateInstaller(); $i.Updates = $c; $res = $i.Install()",
    "  Write-Output ('RESULT:' + $res.ResultCode)",
    "  Write-Output ('REBOOT:' + $res.RebootRequired)",
    "} catch { Write-Output ('ERR:' + $_.Exception.Message) }",
])


class HostUpdateMixin:

    def init_host_update(self):
        cfg = self.config.get("host_update", {}) or {}
        self._host_update_enabled = bool(cfg.get("enabled", True))
        self._host_update_interval = float(cfg.get("check_interval", 3600))
        self._host_update_allow_install = bool(cfg.get("allow_install", True))
        self._host_update_auto_reboot = bool(cfg.get("auto_reboot", False))
        self._host_update_last_count = None
        self._host_update_last_titles = []
        self._host_update_note = ""
        self._host_update_checking = False
        self._host_update_installing = False

    def register_host_update(self):
        if not self._host_update_enabled:
            return
        self._update_discovery(
            "host_update",
            "Windows Updates",
            f"{self.base_topic}/host_update/state",
            command_topic=f"{self.base_topic}/host_update/set" if self._host_update_allow_install else None,
            icon="mdi:microsoft-windows",
            entity_category="diagnostic",
        )
        self._button_discovery(
            "host_update_check",
            "Check Windows Updates",
            f"{self.base_topic}/host_update/check/set",
            icon="mdi:cloud-refresh",
            entity_category="diagnostic",
        )
        self._sensor_discovery(
            "status_updates_available",
            "Updates Available",
            f"{self.base_topic}/updates_available",
            icon="mdi:package-up",
        )
        if self._host_update_last_count is None:
            self._publish_host_update_state(0, in_progress=False)

    def _publish_host_update_state(self, count, in_progress, titles=None):
        count = count if count and count > 0 else 0
        state = {
            "installed_version": "0",
            "latest_version": str(count),
            "title": "Windows Updates",
            "in_progress": in_progress,
        }
        lines = []
        if self._host_update_note:
            lines.append(self._host_update_note)
        if count and titles:
            lines.extend(f"- {t}" for t in titles)
        if lines:
            state["release_summary"] = "\n".join(lines)
        self.publish(f"{self.base_topic}/host_update/state", json.dumps(state), retain=True)

    def handle_host_update_check(self):
        threading.Thread(target=self._run_host_update_check, daemon=True).start()

    def handle_host_update_install(self):
        if not self._host_update_allow_install or self._host_update_installing or self._host_update_checking:
            return
        self._host_update_installing = True
        threading.Thread(target=self._run_host_update_install, daemon=True).start()

    def _run_host_update_install(self):
        self._host_update_note = ""
        self._publish_host_update_state(self._host_update_last_count or 0, in_progress=True, titles=self._host_update_last_titles)
        print("TuxD-Win: installing Windows updates...")
        reboot = False
        try:
            output = run_powershell(_UPDATE_INSTALL_SCRIPT, timeout=7200)
            fields = {}
            for line in output.splitlines():
                key, _, value = line.strip().partition(":")
                if key in ("RESULT", "REBOOT", "ERR"):
                    fields[key] = value.strip()
            if "ERR" in fields:
                self._host_update_note = f"Install failed: {fields['ERR'][:200]}"
            elif fields.get("RESULT") in ("2", "3"):
                reboot = fields.get("REBOOT") == "True"
                if fields["RESULT"] == "3":
                    self._host_update_note = "Some updates installed with errors."
            else:
                self._host_update_note = f"Install did not complete (result {fields.get('RESULT', output.strip()[:100] or 'none')})."
        except Exception as e:
            self._host_update_note = f"Install failed: {e!r}"[:200]
        print(f"TuxD-Win: Windows update install finished. {self._host_update_note}".strip())

        if reboot:
            if self._host_update_auto_reboot:
                self._host_update_note = "Restarting to finish installing updates."
                try:
                    subprocess.run(["shutdown", "/r", "/t", "60", "/c", "TuxD-Win: restarting to finish Windows updates"], timeout=30)
                except Exception as e:
                    self._host_update_note = f"Restart required (automatic restart failed: {e!r})"[:200]
            else:
                self._host_update_note = (self._host_update_note + " " if self._host_update_note else "") + "Restart required to finish installing updates."
        self._host_update_installing = False
        self._run_host_update_check()

    def _run_host_update_check(self):
        if self._host_update_checking or self._host_update_installing:
            return
        self._host_update_checking = True
        self._publish_host_update_state(self._host_update_last_count or 0, in_progress=True, titles=self._host_update_last_titles)
        count = -1
        titles = []
        try:
            output = run_powershell(_UPDATE_CHECK_SCRIPT, timeout=180)
            lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
            if lines:
                count = int(lines[0])
                titles = lines[1:_MAX_LISTED_UPDATES + 1] if count > 0 else []
        except Exception as e:
            print(f"TuxD-Win: Windows Update check failed: {e!r}")
        finally:
            self._host_update_checking = False
        if count >= 0:
            self._host_update_last_count = count
            self._host_update_last_titles = titles
            self.publish(f"{self.base_topic}/updates_available", f"{count} new updates")
        self._publish_host_update_state(max(self._host_update_last_count or 0, 0), in_progress=False, titles=self._host_update_last_titles)

    def host_update_loop(self):
        if not self._host_update_enabled:
            return
        while not self._stop_event.is_set():
            self._run_host_update_check()
            self._stop_event.wait(timeout=self._host_update_interval)
