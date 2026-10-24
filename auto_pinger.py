#!/usr/bin/env python3
"""
AUTO PING'ER UTILITY
====================

Pings one or more IP addresses / host names on a fixed interval and records
the results to a size-limited, rotating local log file.

All settings are read from a JSON file (``config.json`` by default) located in
the same folder as this script. See README.md for details.

Only the Python standard library is used. On Windows the built-in ``ping.exe``
is called, so no administrator rights and no extra packages are required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

BANNER = (
    "AUTO PING\u2019ER UTILITY PYTHON SCRIPT BY ERIC MCFALL 2026, "
    "https://github.com/ericmcfall/auto-pinger"
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.json"

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

FAILED_TEXT = "FAILED PING"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
VALID_LOG_MODES = ("all", "failures")

# Extra seconds allowed for the ping process itself (DNS lookup, process
# start-up) on top of the configured response timeout before it is killed.
PROCESS_GRACE_SECONDS = 10

# Matches the round-trip time in a ping *reply* line, e.g.
#   Windows (any language): "time=14ms", "time<1ms", "Zeit=14ms", "temps=14 ms"
#   Linux / macOS:          "time=14.2 ms"
# A word character must sit directly before '=' or '<' with no space after it.
# This deliberately does NOT match the Windows statistics line
# ("Minimum = 14ms, Maximum = 14ms, Average = 14ms"), which has spaces.
REPLY_TIME_RE = re.compile(r"\w([=<])(\d+(?:[.,]\d+)?)\s?ms\b", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class ConfigError(Exception):
    """Raised when the JSON settings file is missing or invalid."""


@dataclass
class Config:
    targets: List[str]
    interval_seconds: float
    timeout_seconds: float
    max_log_size_mb: float
    log_file_count: int
    log_file_path: Path
    log_mode: str

    @property
    def max_log_bytes(self) -> int:
        return max(1, int(self.max_log_size_mb * 1024 * 1024))


def _require_number(data: dict, key: str, minimum_exclusive: float = 0) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f'"{key}" must be a number (got {value!r}).')
    if value <= minimum_exclusive:
        raise ConfigError(f'"{key}" must be greater than {minimum_exclusive} (got {value}).')
    return float(value)


def load_config(path: Path) -> Config:
    """Read and validate the JSON settings file."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Settings file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Settings file is not valid JSON: {path}\n"
            f"  Line {exc.lineno}, column {exc.colno}: {exc.msg}\n"
            "  (Tip: Windows paths need double backslashes, e.g. "
            '"C:\\\\Logs\\\\ping.log", or use forward slashes "C:/Logs/ping.log".)'
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError("Settings file must contain a JSON object { ... }.")

    required = (
        "targets", "interval_seconds", "timeout_seconds", "max_log_size_mb",
        "log_file_count", "log_file_path",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise ConfigError("Settings file is missing: " + ", ".join(f'"{k}"' for k in missing))

    # targets: list of strings (a single string is also accepted)
    targets = data["targets"]
    if isinstance(targets, str):
        targets = [targets]
    if not isinstance(targets, list) or not targets:
        raise ConfigError('"targets" must be a list with at least one IP address or host name.')
    clean_targets: List[str] = []
    for t in targets:
        if not isinstance(t, str) or not t.strip():
            raise ConfigError(f'Every entry in "targets" must be a non-empty text value (got {t!r}).')
        t = t.strip()
        if t.startswith("-") or any(ch.isspace() for ch in t):
            raise ConfigError(f'Invalid target {t!r}: must not start with "-" or contain spaces.')
        if "://" in t or "/" in t:
            raise ConfigError(
                f'Invalid target {t!r}: use a bare host name or IP (e.g. "example.com"), '
                "not a URL."
            )
        clean_targets.append(t)

    interval = _require_number(data, "interval_seconds")
    timeout = _require_number(data, "timeout_seconds")
    max_mb = _require_number(data, "max_log_size_mb")

    count = data["log_file_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ConfigError(f'"log_file_count" must be a whole number of 1 or more (got {count!r}).')

    log_path_raw = data["log_file_path"]
    if not isinstance(log_path_raw, str) or not log_path_raw.strip():
        raise ConfigError('"log_file_path" must be a non-empty path, e.g. "logs/auto_pinger.log".')
    log_path = Path(os.path.expandvars(os.path.expanduser(log_path_raw.strip())))
    if not log_path.is_absolute():
        # Relative paths are relative to the folder that holds the settings file.
        log_path = path.resolve().parent / log_path
    if log_path.name in ("", ".", ".."):
        raise ConfigError('"log_file_path" must include a file name, e.g. "logs/auto_pinger.log".')

    log_mode = data.get("log_mode", "all")
    if not isinstance(log_mode, str) or log_mode.strip().lower() not in VALID_LOG_MODES:
        raise ConfigError(f'"log_mode" must be "all" or "failures" (got {log_mode!r}).')

    return Config(
        targets=clean_targets,
        interval_seconds=interval,
        timeout_seconds=timeout,
        max_log_size_mb=max_mb,
        log_file_count=count,
        log_file_path=log_path,
        log_mode=log_mode.strip().lower(),
    )


# --------------------------------------------------------------------------- #
# Ping
# --------------------------------------------------------------------------- #
@dataclass
class PingResult:
    timestamp: datetime
    target: str
    success: bool
    rtt_ms: Optional[float] = None   # None when no reply was received
    rtt_below_1ms: bool = False      # Windows reports "time<1ms"
    reason: str = ""                 # why the ping failed (empty on success)


def build_ping_command(target: str, timeout_seconds: float, platform: Optional[str] = None) -> List[str]:
    """Return the OS ping command for a single echo request."""
    platform = platform or ("windows" if IS_WINDOWS else "mac" if IS_MAC else "linux")
    if platform == "windows":
        # -n 1 : one echo request     -w : reply timeout in milliseconds
        timeout_ms = max(1, int(round(timeout_seconds * 1000)))
        return ["ping", "-n", "1", "-w", str(timeout_ms), target]
    if platform == "mac":
        # -c 1 : one request          -W : reply timeout in milliseconds
        timeout_ms = max(1, int(round(timeout_seconds * 1000)))
        return ["ping", "-c", "1", "-W", str(timeout_ms), target]
    # Linux (iputils): -W is the reply timeout in whole seconds
    return ["ping", "-c", "1", "-W", str(max(1, int(-(-timeout_seconds // 1)))), target]


def _failure_reason(output: str) -> str:
    text = output.lower()
    if ("could not find host" in text or "name or service not known" in text
            or "temporary failure in name resolution" in text
            or "cannot resolve" in text or "unknown host" in text):
        return "could not resolve host"
    if "unreachable" in text:
        return "destination unreachable"
    if "ttl expired" in text or "time to live exceeded" in text:
        return "TTL expired in transit"
    if "general failure" in text:
        return "general failure"
    if "timed out" in text or "100% packet loss" in text or "100.0% packet loss" in text:
        return "timed out"
    return "no reply"


def parse_ping_output(output: str, target: str, timeout_seconds: float,
                      timestamp: Optional[datetime] = None) -> PingResult:
    """Interpret ping output.

    Success requires a reply line that carries a round-trip time. Exit codes
    are ignored on purpose: Windows ping returns 0 for "Destination host
    unreachable" replies sent by a router.
    """
    timestamp = timestamp or datetime.now()
    for line in output.splitlines():
        match = REPLY_TIME_RE.search(line)
        if not match:
            continue
        below_1 = match.group(1) == "<"
        rtt = float(match.group(2).replace(",", "."))
        if below_1:
            rtt = min(rtt, 1.0)
        limit_ms = timeout_seconds * 1000.0
        if rtt > limit_ms:
            return PingResult(timestamp, target, False, rtt, below_1,
                              f"exceeded {format_seconds(timeout_seconds)} s limit")
        return PingResult(timestamp, target, True, rtt, below_1)
    return PingResult(timestamp, target, False, None, False, _failure_reason(output))


def ping(target: str, timeout_seconds: float) -> PingResult:
    """Send one ping to *target* and return the result. Never raises for network errors."""
    timestamp = datetime.now()
    cmd = build_ping_command(target, timeout_seconds)
    kwargs = {}
    if IS_WINDOWS:
        # Prevent a console window flashing up when run with pythonw.exe.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
            timeout=timeout_seconds + PROCESS_GRACE_SECONDS,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return PingResult(timestamp, target, False, None, False, "ping command did not finish")
    except FileNotFoundError:
        raise RuntimeError("The system 'ping' command was not found on this computer.")
    return parse_ping_output(proc.stdout or "", target, timeout_seconds, timestamp)


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def format_seconds(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def format_ms(result: PingResult) -> str:
    if result.rtt_ms is None:
        return "-- ms"
    if result.rtt_below_1ms:
        return "<1 ms"
    if float(result.rtt_ms).is_integer():
        return f"{int(result.rtt_ms)} ms"
    return f"{result.rtt_ms:.1f} ms"


def format_result(result: PingResult, target_width: int = 0) -> str:
    """One log/console line: date time | target | response ms [| FAILED PING (reason)]"""
    parts = [
        result.timestamp.strftime(TIMESTAMP_FORMAT),
        result.target.ljust(target_width),
        format_ms(result).rjust(7),
    ]
    if not result.success:
        parts.append(f"{FAILED_TEXT} ({result.reason})" if result.reason else FAILED_TEXT)
    return " | ".join(parts).rstrip()


# --------------------------------------------------------------------------- #
# Rotating log file
# --------------------------------------------------------------------------- #
class RotatingLog:
    """Append-only text log limited by size and number of files.

    Files for "logs/auto_pinger.log" with log_file_count = 3:
        auto_pinger.log     <- current (newest)
        auto_pinger.1.log
        auto_pinger.2.log   <- oldest; deleted on the next rotation

    The file is opened and closed for every write so it can be viewed in
    another program while the script runs.
    """

    def __init__(self, path: Path, max_bytes: int, file_count: int, warn=None):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.file_count = int(file_count)
        self._warn = warn or (lambda msg: print(f"WARNING: {msg}", flush=True))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prune_extra_files()

    def numbered_path(self, index: int) -> Path:
        if index == 0:
            return self.path
        return self.path.with_name(f"{self.path.stem}.{index}{self.path.suffix}")

    def existing_files(self) -> List[Path]:
        """All log files belonging to this log, newest first."""
        pattern = re.compile(
            r"^" + re.escape(self.path.stem) + r"\.(\d+)" + re.escape(self.path.suffix) + r"$"
        )
        numbered = []
        for p in self.path.parent.iterdir():
            m = pattern.match(p.name)
            if m and p.is_file():
                numbered.append((int(m.group(1)), p))
        files = [self.path] if self.path.is_file() else []
        files += [p for _, p in sorted(numbered)]
        return files

    def prune_extra_files(self) -> None:
        """Delete numbered files beyond log_file_count (e.g. after lowering the setting)."""
        pattern = re.compile(
            r"^" + re.escape(self.path.stem) + r"\.(\d+)" + re.escape(self.path.suffix) + r"$"
        )
        for p in self.path.parent.iterdir():
            m = pattern.match(p.name)
            if m and int(m.group(1)) >= self.file_count:
                try:
                    p.unlink()
                except OSError as exc:
                    self._warn(f"could not delete old log file {p}: {exc}")

    def rotate(self) -> bool:
        try:
            if self.file_count <= 1:
                # Only one file allowed: start it over.
                open(self.path, "w", encoding="utf-8").close()
                return True
            oldest = self.numbered_path(self.file_count - 1)
            if oldest.exists():
                oldest.unlink()
            for i in range(self.file_count - 2, -1, -1):
                src = self.numbered_path(i)
                if src.exists():
                    os.replace(src, self.numbered_path(i + 1))
            return True
        except OSError as exc:
            self._warn(f"could not rotate log file (is it open in another program?): {exc}")
            return False

    def write(self, line: str) -> None:
        data_len = len((line + os.linesep).encode("utf-8"))
        try:
            size = self.path.stat().st_size if self.path.exists() else 0
            if size > 0 and size + data_len > self.max_bytes:
                self.rotate()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            self._warn(f"could not write to log file {self.path}: {exc}")


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def should_log(result: PingResult, log_mode: str) -> bool:
    return log_mode == "all" or not result.success


def run_cycle(config: Config, log: RotatingLog, executor: ThreadPoolExecutor,
              ping_func=None, out=None) -> List[PingResult]:
    """Ping every target once (in parallel), print and log the results in target order."""
    ping_func = ping_func or ping
    out = out or (lambda line: print(line, flush=True))
    futures = [executor.submit(ping_func, t, config.timeout_seconds) for t in config.targets]
    pending = set(futures)
    while pending:
        # Short waits keep Ctrl+C responsive on Windows.
        _, pending = wait(pending, timeout=0.25)
    width = max(len(t) for t in config.targets)
    results = []
    for fut in futures:
        result = fut.result()
        results.append(result)
        line = format_result(result, width)
        out(line)
        if should_log(result, config.log_mode):
            log.write(line)
    return results


def describe_config(config: Config, config_path: Path) -> str:
    rows = [
        ("Settings file", str(config_path)),
        ("Targets", ", ".join(config.targets)),
        ("Interval", f"{format_seconds(config.interval_seconds)} s"),
        ("Timeout", f"{format_seconds(config.timeout_seconds)} s"),
        ("Log file", str(config.log_file_path)),
        ("Log size / count", f"{config.max_log_size_mb:g} MB x {config.log_file_count} file(s)"),
        ("Log mode", "all pings" if config.log_mode == "all" else "failures only"),
    ]
    return "\n".join(f"  {k:<17}: {v}" for k, v in rows)


def _pause_on_error() -> None:
    # Keeps the window open long enough to read the error when the script was
    # started by double-clicking it in Windows Explorer.
    if IS_WINDOWS and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nPress Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on an unprintable character
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description="Auto Ping'er - ping hosts on an interval and log the results.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                        help="path to the JSON settings file (default: config.json next to this script)")
    parser.add_argument("--once", action="store_true",
                        help="ping every target one time, then exit (useful for testing)")
    args = parser.parse_args(argv)

    print(BANNER, flush=True)
    print(flush=True)

    config_path = Path(args.config).resolve()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"SETTINGS ERROR: {exc}", file=sys.stderr, flush=True)
        _pause_on_error()
        return 2

    print(describe_config(config, config_path), flush=True)
    print("\nPress Ctrl+C to stop.\n", flush=True)

    try:
        log = RotatingLog(config.log_file_path, config.max_log_bytes, config.log_file_count)
    except OSError as exc:
        print(f"ERROR: cannot use log file location {config.log_file_path}: {exc}", file=sys.stderr, flush=True)
        _pause_on_error()
        return 3

    if config.timeout_seconds >= config.interval_seconds:
        print("NOTE: timeout_seconds is not less than interval_seconds; failed pings will "
              "delay the next cycle beyond the configured interval.\n", flush=True)

    started = datetime.now().strftime(TIMESTAMP_FORMAT)
    log.write(f"# {started} | session started | targets: {', '.join(config.targets)}")

    executor = ThreadPoolExecutor(max_workers=len(config.targets))
    exit_code = 0
    try:
        next_run = time.monotonic()
        while True:
            run_cycle(config, log, executor)
            if args.once:
                break
            next_run += config.interval_seconds
            delay = next_run - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_run = time.monotonic()  # cycle overran; start the next one now
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        _pause_on_error()
        exit_code = 4
    finally:
        executor.shutdown(wait=False)
        stopped = datetime.now().strftime(TIMESTAMP_FORMAT)
        log.write(f"# {stopped} | session stopped")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
