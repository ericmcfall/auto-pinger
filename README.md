# Auto Ping'er

A small Python utility that pings one or more IP addresses or host names on a fixed interval and records every result (or only failures) to a size-limited, rotating text log. Built for monitoring network devices — displays, processors, switches, media servers — on Windows show and venue networks.

- Uses only the Python standard library — **no `pip install` needed**
- Calls Windows' built-in `ping.exe` — **no administrator rights needed**
- All settings live in `config.json` next to the script
- Multiple targets are pinged **in parallel** each cycle
- Log files rotate by size and the number of files kept is capped

---

## Contents

- [Requirements](#requirements)
- [Install on Windows](#install-on-windows)
- [Configure `config.json`](#configure-configjson)
- [Run it](#run-it)
- [Log file format](#log-file-format)
- [Log rotation](#log-rotation)
- [Run automatically at Windows startup](#run-automatically-at-windows-startup)
- [Troubleshooting](#troubleshooting)
- [Running the tests](#running-the-tests)

---

## Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10 or Windows 11 (also works on macOS / Linux) |
| Python | 3.9 or newer, from [python.org](https://www.python.org/downloads/windows/) |
| Packages | None (standard library only) |
| Permissions | Normal user — no admin rights |

---

## Install on Windows

### 1. Install Python

1. Download the latest **Windows installer (64-bit)** from <https://www.python.org/downloads/windows/>.
2. Run the installer. On the first screen, **tick "Add python.exe to PATH"**, then click **Install Now**.
3. Open **Command Prompt** (press <kbd>Win</kbd>, type `cmd`, press <kbd>Enter</kbd>) and confirm:

   ```bat
   py --version
   ```

   You should see `Python 3.x.x`. (`python --version` also works if PATH was set.)

> **Microsoft Store pop-up?** If typing `python` opens the Microsoft Store, either use `py` instead, or turn off the aliases: **Settings → Apps → Advanced app settings → App execution aliases** → switch off *python.exe* and *python3.exe*.

### 2. Get Auto Ping'er

**Option A — download ZIP:** on the GitHub page click **Code → Download ZIP**, then right-click the ZIP → **Extract All…** to a folder such as `C:\Tools\auto-pinger`.

**Option B — git:**

```bat
cd C:\Tools
git clone https://github.com/ericmcfall/auto-pinger.git
```

The folder should contain:

```
auto-pinger\
├── auto_pinger.py        the script
├── config.json           settings (edit this)
├── run_auto_pinger.bat   double-click launcher
├── README.md
└── tests\
```

---

## Configure `config.json`

Open `config.json` in Notepad (or any text editor) in the same folder as `auto_pinger.py`:

```json
{
  "targets": ["8.8.8.8", "google.com"],
  "interval_seconds": 5,
  "timeout_seconds": 2,
  "max_log_size_mb": 5,
  "log_file_count": 5,
  "log_file_path": "logs/auto_pinger.log",
  "log_mode": "all"
}
```

| Setting | Type | Description |
|---|---|---|
| `targets` | list of text | IP addresses and/or host names to ping, e.g. `["192.168.1.50", "projector-01.local", "google.com"]`. Use bare names only — not `https://…` URLs. A single value `"10.0.0.5"` is also accepted. |
| `interval_seconds` | number | Seconds between the **start** of each ping cycle. Decimals allowed (`0.5`). |
| `timeout_seconds` | number | Seconds to wait for a reply. No reply in time, or a reply slower than this, is logged as `FAILED PING`. Decimals allowed. |
| `max_log_size_mb` | number | Maximum size of each log file in megabytes. Decimals allowed (`0.5` = 512 KB). |
| `log_file_count` | whole number | Total number of log files to keep, **including** the current one. Minimum `1`. |
| `log_file_path` | text | Folder and file name of the log. Relative paths are relative to the folder containing `config.json`. The folder is created automatically. |
| `log_mode` | `"all"` or `"failures"` | `"all"` logs every ping. `"failures"` logs only `FAILED PING` lines. Optional; default `"all"`. The console always shows every ping. |

### Windows paths in JSON

JSON treats `\` as a special character. Use **forward slashes** or **double backslashes**:

```json
"log_file_path": "C:/PingLogs/stage-network.log"
"log_file_path": "C:\\PingLogs\\stage-network.log"
```

Environment variables work too: `"%USERPROFILE%/Documents/ping.log"`.

### Choosing interval and timeout

All targets in a cycle are pinged at the same time, so one cycle takes at most `timeout_seconds`. Keep `timeout_seconds` **lower** than `interval_seconds`; if it is not, the script warns you and a failing target will stretch the cycle past the interval.

---

## Run it

### Option 1 — double-click

Double-click **`run_auto_pinger.bat`**. A console window opens and stays open; press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop.

### Option 2 — Command Prompt

```bat
cd C:\Tools\auto-pinger
py auto_pinger.py
```

### Option 3 — PowerShell

```powershell
Set-Location C:\Tools\auto-pinger
py .\auto_pinger.py
```

### Command-line options

| Option | Purpose |
|---|---|
| `--config PATH` | Use a different settings file, e.g. `py auto_pinger.py --config C:\Configs\stage-b.json`. Lets you run several independent copies with different targets and logs. |
| `--once` | Ping every target one time, then exit. Good for checking a new config. |

### Console output

```
AUTO PING’ER UTILITY PYTHON SCRIPT BY ERIC MCFALL 2026, https://github.com/ericmcfall/auto-pinger

  Settings file    : C:\Tools\auto-pinger\config.json
  Targets          : 8.8.8.8, google.com
  Interval         : 5 s
  Timeout          : 2 s
  Log file         : C:\Tools\auto-pinger\logs\auto_pinger.log
  Log size / count : 5 MB x 5 file(s)
  Log mode         : all pings

Press Ctrl+C to stop.

2026-10-24 13:55:01 | 8.8.8.8    |   14 ms
2026-10-24 13:55:01 | google.com |   23 ms
```

Stop with <kbd>Ctrl</kbd>+<kbd>C</kbd>. The script writes a `session stopped` line to the log and exits.

---

## Log file format

One line per ping, fields separated by ` | `:

```
date time           | target     | response | result
```

```
# 2026-10-24 13:55:01 | session started | targets: 8.8.8.8, google.com, 10.0.0.250
2026-10-24 13:55:01 | 8.8.8.8    |   14 ms
2026-10-24 13:55:01 | google.com |   23 ms
2026-10-24 13:55:01 | 10.0.0.250 |   -- ms | FAILED PING (timed out)
2026-10-24 13:55:06 | 8.8.8.8    |   <1 ms
2026-10-24 13:55:06 | google.com | 2350 ms | FAILED PING (exceeded 2 s limit)
2026-10-24 13:55:06 | 10.0.0.250 |   -- ms | FAILED PING (destination unreachable)
# 2026-10-24 14:10:44 | session stopped
```

| Field | Meaning |
|---|---|
| date time | Local time the ping was sent (`YYYY-MM-DD HH:MM:SS`) |
| target | IP address or host name pinged |
| response | Round-trip time in milliseconds. `<1 ms` = under one millisecond (as reported by Windows). `-- ms` = no reply. |
| `FAILED PING (reason)` | Present only on failure. Reasons: `timed out`, `destination unreachable`, `could not resolve host`, `TTL expired in transit`, `general failure`, `exceeded N s limit` (a reply arrived but slower than `timeout_seconds`), `no reply` (anything else, e.g. non-English Windows messages). |

Lines starting with `#` mark when monitoring started and stopped, so gaps in monitoring are visible.

To find failures quickly in Command Prompt:

```bat
findstr /C:"FAILED PING" logs\auto_pinger*.log
```

PowerShell:

```powershell
Select-String -Path .\logs\auto_pinger*.log -Pattern "FAILED PING"
```

---

## Log rotation

With `"log_file_path": "logs/auto_pinger.log"`, `"max_log_size_mb": 5` and `"log_file_count": 3`:

```
logs\auto_pinger.log      current (newest)
logs\auto_pinger.1.log    previous
logs\auto_pinger.2.log    oldest
```

When the current file would exceed 5 MB, each file shifts down one number, the oldest is deleted and a new current file starts. Total disk use is capped at about `max_log_size_mb × log_file_count`.

- `log_file_count: 1` keeps a single file that is cleared and restarted when it reaches the limit.
- If you lower `log_file_count`, extra numbered files are deleted the next time the script starts.
- The log file is opened only for each write, so you can view it in Notepad while the script is running. Programs that lock files (e.g. Excel) can block rotation; the script prints a warning and keeps going.

---

## Run automatically at Windows startup

Using **Task Scheduler** (no admin rights required for your own account):

1. Press <kbd>Win</kbd>, type **Task Scheduler**, open it → **Create Task…**
2. **General:** name it `Auto Pinger`. Choose *Run only when user is logged on* to see the console window.
3. **Triggers:** **New… → At log on** (or *At startup*).
4. **Actions:** **New… → Start a program**
   - Program/script: `C:\Tools\auto-pinger\run_auto_pinger.bat`
   - Start in: `C:\Tools\auto-pinger`
5. **Settings:** untick *Stop the task if it runs longer than 3 days*.

To run hidden in the background instead, set Program/script to `pyw` (or `pythonw.exe`) with arguments `auto_pinger.py`. There is no console in that mode; check the log file, and stop it from Task Manager (`pythonw.exe`).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `'py' is not recognized` / `'python' is not recognized` | Python is not installed or not on PATH. Re-run the installer, choose **Modify**, and enable *Add Python to environment variables*. |
| Window flashes and closes | Run from Command Prompt or use `run_auto_pinger.bat` so you can read the message. |
| `SETTINGS ERROR: … not valid JSON` | Check commas, quotes and brackets. Windows paths need `/` or `\\`. |
| Every ping to a device shows `FAILED PING (timed out)` but the device works | The device or its firewall may block ICMP echo (ping). Windows PCs block inbound ping by default; enable *File and Printer Sharing (Echo Request - ICMPv4-In)* in Windows Defender Firewall on the **target** PC. |
| `could not resolve host` | The host name cannot be found by DNS. Check spelling, or use the IP address. |
| `WARNING: could not rotate log file` | Another program has the log file locked. Close it; rotation is retried on the next write. |
| `no reply` reasons on non-English Windows | Response times are still detected in any language; only the failure reason text is English-only, so unknown messages show as `no reply`. |

---

## Running the tests

From the project folder:

```bat
py -m unittest discover -s tests -v
```

The suite covers ping-output parsing (real Windows `ping.exe` samples, including localized output and the "Destination host unreachable" case where Windows returns success), the slow-reply limit, settings validation, log rotation, log modes, and full script runs against `127.0.0.1`. Tests also run automatically on Windows via GitHub Actions on every push.

---

## License

MIT — see [LICENSE](LICENSE).
