# TuxD-Win

A "lite" Windows counterpart to [TuxD](../TuxD) (the Linux agent) - reports
a Windows host/VM to the same [TuxD-HA](../TuxD-HA) Home Assistant
integration, over the exact same `connection_mode: direct` WebSocket
protocol and entity-naming conventions. A Windows device shows up in
TuxD-Cards' device grid, the Fleet Summary card, and TuxD-HA's
threshold/fleet-count sensors exactly like a Linux one - no changes needed
on the integration side, because the wire protocol and object_ids
(`cpu_load`, `memory_used_percent`, `network_in_out`, `storage_used_*`,
`host_update`, `self_update`) are byte-for-byte the same ones TuxD uses.

## What it does

- CPU / memory / combined network throughput, plus disk usage per monitored
  drive (used %, used GB, free GB) and combined across all of them. Per-drive
  sensors are named like TuxD's per-disk ones: C:\ is "root"
  (`sensor.<host>_root_storage_used`), any other drive by its letter
  (`sensor.<host>_d_storage_used`).
- On a Windows VM, an optional `metrics.host_cpu_load` sensor
  (`sensor.<host>_host_cpu_load`) - the VM's CPU use as a share of the
  physical host (`cpu_load * VM cores / host_cores`), same as TuxD's
  `cpu_load.host_cpu_load`. Off by default; set `host_cores` to the
  hypervisor's logical core count.
- One binary_sensor per Windows service you list in `tuxd-win.conf`
  (`sc.exe`-style name, e.g. `Spooler`, `wuauserv` - not the display name),
  ON/OFF for running/not, with the real status string as an attribute.
- Windows Update detection (via the built-in `Microsoft.Update.Session` COM
  API - no extra module needed) as an `update` entity, so pending patches
  count toward TuxD-HA's fleet-wide "Devices With Host Updates" sensor, plus
  `sensor.<host>_updates_available` ("N new updates", same as on TuxD hosts).
  **Detection only** - it never installs a Windows Update itself (see
  `modules/host_update_agent.py`'s docstring for why).
- Self-update from this project's own GitHub releases, same as TuxD updates
  itself - `Install` shows up as an entity action once a new release exists.
- Restart / Force Refresh buttons, and remote `tuxd-win.conf` editing
  through TuxD-HA's existing "Edit device configuration" screen (it just
  speaks the same get/set protocol - it doesn't know or care what platform
  is on the other end).

## What it deliberately doesn't do

No interactive terminal / live shell (TuxD's `terminal`/`live_tty`
features) - this is a monitoring-and-management agent, not a remote
console. No Docker monitoring (Docker Desktop on a Windows host wasn't the
target use case - it's for monitoring the host/VM itself, e.g. a
hypervisor host, not the containers running on separate Linux VMs it
already manages via TuxD). No SMART disk data, no per-NIC breakdown, no
release channels (always tracks GitHub's latest release) - "lite" means
picking the handful of things that matter most for a host machine, not
porting every TuxD feature.

## Setup

1. Install [Python 3.9+](https://python.org).
2. Copy this whole folder onto the Windows host.
3. From an elevated PowerShell, in this folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File install-windows.ps1
   ```
   This installs `websockets`/`pyyaml`/`psutil`, then checks that SYSTEM can
   actually launch the interpreter and import those packages (a one-shot
   self-test task) *before* registering a Scheduled Task (`TuxD-Win`, runs
   at boot as SYSTEM, restarts the agent itself whenever it exits). It does
   **not** start it yet (unless the task was already running - then it is
   stopped and started again on the new definition), and never overwrites an
   existing `tuxd-win.conf`.

   A Microsoft Store / Python install manager `python.exe` under
   `WindowsApps` is only a launcher alias: it runs fine in your shell but
   Task Scheduler can't launch it as SYSTEM (`0x80070780`). The installer
   resolves the real interpreter behind it (`sys.executable`) and rejects
   any `WindowsApps` path; if it can't find a usable one it says so and
   stops, and `-PythonPath "C:\path\to\python.exe"` overrides discovery.
4. Edit `tuxd-win.conf` (created from `tuxd-win.conf.example` on first
   install): set `device.name`, `home-assistant.url` and
   `home-assistant.pairing_key` (from TuxD-HA's setup screen), and list any
   Windows services you want monitored under `services.names`.
5. Start it:
   ```powershell
   Start-ScheduledTask -TaskName TuxD-Win
   ```
6. Approve the new device from TuxD-HA's Configure > Review new devices,
   the same as any TuxD device.

## Re-running for testing

`python windows_start.py` runs it directly in a console (set
`device.tty_output: true` in `tuxd-win.conf` to see connection/discovery
activity) - useful before committing to the Scheduled Task.
`python windows_start.py --selftest` just checks the interpreter, its
packages and write access to this folder, then exits.

## Architecture notes (for anyone maintaining this alongside TuxD)

`modules/shared.py` and `modules/base_direct.py` are near-verbatim copies
of TuxD's own `modules/agent/shared.py`/`base_direct.py` - both are already
fully OS-agnostic Python (asyncio + websockets + json), so this is what
guarantees the wire protocol and entity_id derivation (`slugify`,
`entity_object_id`) never drift between the two agents. If you fix a bug in
one connection layer, check whether the same fix applies to the other.
`modules/restart.py` is the one deliberate divergence: Windows has no real
`exec()` syscall, so `os.execv` (what TuxD uses) would block the calling
thread instead of replacing the process - this uses a plain `os._exit(1)`
instead, and `windows_start.py` acts as its own supervisor: the process the
Scheduled Task runs never exits, it runs the agent as a child (`--child`)
and starts a new one whenever that exits (2s later; a child that dies
within 5s of starting is retried with a growing delay, capped at 30s). Task
Scheduler's own "restart on failure" setting does NOT relaunch a task whose
program exits with a nonzero code, so nothing here depends on it. The
supervisor is stdlib-only, and a child whose supervisor was killed exits by
itself so two agents can never run at once. `windows_start.py --child` runs
the agent without the supervisor (debugging only - restart then just stops
it). A self-update replaces the files and exits; the supervisor process
itself keeps running its old copy until the task is next restarted, which
only matters if the supervisor code itself changed.
