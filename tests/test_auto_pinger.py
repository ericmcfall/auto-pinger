"""Tests for auto_pinger.py.  Run from the project folder with:

    python -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auto_pinger as ap  # noqa: E402

TS = datetime(2026, 10, 24, 13, 55, 1)

# The script pauses for Enter after an error on Windows consoles; never block tests on it.
_pause_patch = mock.patch.object(ap, "_pause_on_error", lambda: None)


def setUpModule():
    _pause_patch.start()


def tearDownModule():
    _pause_patch.stop()

# ----------------------------------------------------------------------------
# Real Windows ping.exe outputs (ping -n 1 -w 2000 <target>)
# ----------------------------------------------------------------------------
WIN_SUCCESS = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=14ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 14ms, Maximum = 14ms, Average = 14ms
"""

WIN_SUB_1MS = """
Pinging 127.0.0.1 with 32 bytes of data:
Reply from 127.0.0.1: bytes=32 time<1ms TTL=128

Ping statistics for 127.0.0.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 0ms, Average = 0ms
"""

WIN_HOSTNAME = """
Pinging google.com [142.250.72.14] with 32 bytes of data:
Reply from 142.250.72.14: bytes=32 time=23ms TTL=116

Ping statistics for 142.250.72.14:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 23ms, Maximum = 23ms, Average = 23ms
"""

WIN_IPV6 = """
Pinging localhost [::1] with 32 bytes of data:
Reply from ::1: time<1ms

Ping statistics for ::1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 0ms, Average = 0ms
"""

WIN_GERMAN = """
Ping wird ausgeführt für 8.8.8.8 mit 32 Bytes Daten:
Antwort von 8.8.8.8: Bytes=32 Zeit=15ms TTL=117

Ping-Statistik für 8.8.8.8:
    Pakete: Gesendet = 1, Empfangen = 1, Verloren = 0
    (0% Verlust),
Ca. Zeitangaben in Millisek.:
    Minimum = 15ms, Maximum = 15ms, Mittelwert = 15ms
"""

WIN_TIMEOUT = """
Pinging 10.0.0.250 with 32 bytes of data:
Request timed out.

Ping statistics for 10.0.0.250:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""

# Windows returns exit code 0 for this one, so exit codes cannot be trusted.
WIN_UNREACHABLE = """
Pinging 10.9.9.9 with 32 bytes of data:
Reply from 192.168.1.1: Destination host unreachable.

Ping statistics for 10.9.9.9:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

WIN_DNS_FAIL = "Ping request could not find host nothing.invalid. Please check the name and try again.\n"

WIN_TTL_EXPIRED = """
Pinging 10.1.1.1 with 32 bytes of data:
Reply from 192.168.1.1: TTL expired in transit.

Ping statistics for 10.1.1.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""

WIN_GENERAL_FAILURE = """
Pinging 10.1.1.1 with 32 bytes of data:
General failure.

Ping statistics for 10.1.1.1:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""

WIN_SLOW = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=2350ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 2350ms, Maximum = 2350ms, Average = 2350ms
"""

LINUX_SUCCESS = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=14.2 ms

--- 8.8.8.8 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 14.200/14.200/14.200/0.000 ms
"""

LINUX_TIMEOUT = """PING 10.0.0.250 (10.0.0.250) 56(84) bytes of data.

--- 10.0.0.250 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
"""


def write_config(folder: Path, **overrides) -> Path:
    data = {
        "targets": ["127.0.0.1"],
        "interval_seconds": 1,
        "timeout_seconds": 1,
        "max_log_size_mb": 1,
        "log_file_count": 3,
        "log_file_path": "logs/test.log",
        "log_mode": "all",
    }
    data.update(overrides)
    path = folder / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ----------------------------------------------------------------------------
class TestBanner(unittest.TestCase):
    def test_banner_text_exact(self):
        self.assertEqual(
            ap.BANNER,
            "AUTO PING\u2019ER UTILITY PYTHON SCRIPT BY ERIC MCFALL 2026, "
            "https://github.com/ericmcfall/auto-pinger",
        )

    def test_banner_printed_first(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            ap.main(["--config", str(Path(tempfile.gettempdir()) / "no_such_auto_pinger.json")])
        self.assertEqual(out.getvalue().splitlines()[0], ap.BANNER)


# ----------------------------------------------------------------------------
class TestPingCommand(unittest.TestCase):
    def test_windows_command(self):
        self.assertEqual(ap.build_ping_command("8.8.8.8", 2, "windows"),
                         ["ping", "-n", "1", "-w", "2000", "8.8.8.8"])

    def test_windows_fractional_timeout(self):
        self.assertEqual(ap.build_ping_command("h", 0.5, "windows")[4], "500")

    def test_linux_command_rounds_up(self):
        self.assertEqual(ap.build_ping_command("h", 1.2, "linux"), ["ping", "-c", "1", "-W", "2", "h"])
        self.assertEqual(ap.build_ping_command("h", 0.3, "linux")[4], "1")

    def test_mac_command(self):
        self.assertEqual(ap.build_ping_command("h", 2, "mac"), ["ping", "-c", "1", "-W", "2000", "h"])


# ----------------------------------------------------------------------------
class TestParsing(unittest.TestCase):
    def parse(self, text, timeout=2):
        return ap.parse_ping_output(text, "t", timeout, TS)

    def test_success(self):
        r = self.parse(WIN_SUCCESS)
        self.assertTrue(r.success)
        self.assertEqual(r.rtt_ms, 14)

    def test_sub_1ms(self):
        r = self.parse(WIN_SUB_1MS)
        self.assertTrue(r.success)
        self.assertTrue(r.rtt_below_1ms)
        self.assertEqual(ap.format_ms(r), "<1 ms")

    def test_hostname(self):
        self.assertEqual(self.parse(WIN_HOSTNAME).rtt_ms, 23)

    def test_ipv6_reply_has_no_ttl(self):
        r = self.parse(WIN_IPV6)
        self.assertTrue(r.success)
        self.assertTrue(r.rtt_below_1ms)

    def test_localized_windows(self):
        r = self.parse(WIN_GERMAN)
        self.assertTrue(r.success)
        self.assertEqual(r.rtt_ms, 15)

    def test_statistics_line_not_mistaken_for_reply(self):
        stats_only = "    Minimum = 14ms, Maximum = 14ms, Average = 14ms\n"
        self.assertFalse(self.parse(stats_only).success)

    def test_timeout(self):
        r = self.parse(WIN_TIMEOUT)
        self.assertFalse(r.success)
        self.assertIsNone(r.rtt_ms)
        self.assertEqual(r.reason, "timed out")

    def test_unreachable_is_failure(self):
        r = self.parse(WIN_UNREACHABLE)
        self.assertFalse(r.success)
        self.assertEqual(r.reason, "destination unreachable")

    def test_dns_failure(self):
        r = self.parse(WIN_DNS_FAIL)
        self.assertFalse(r.success)
        self.assertEqual(r.reason, "could not resolve host")

    def test_ttl_expired(self):
        self.assertEqual(self.parse(WIN_TTL_EXPIRED).reason, "TTL expired in transit")

    def test_general_failure(self):
        self.assertEqual(self.parse(WIN_GENERAL_FAILURE).reason, "general failure")

    def test_slow_reply_over_limit_fails_but_keeps_time(self):
        r = self.parse(WIN_SLOW, timeout=2)
        self.assertFalse(r.success)
        self.assertEqual(r.rtt_ms, 2350)
        self.assertEqual(r.reason, "exceeded 2 s limit")

    def test_slow_reply_within_limit_passes(self):
        self.assertTrue(self.parse(WIN_SLOW, timeout=3).success)

    def test_linux_output(self):
        r = self.parse(LINUX_SUCCESS)
        self.assertTrue(r.success)
        self.assertAlmostEqual(r.rtt_ms, 14.2)
        self.assertEqual(self.parse(LINUX_TIMEOUT).reason, "timed out")

    def test_empty_output(self):
        r = self.parse("")
        self.assertFalse(r.success)
        self.assertEqual(r.reason, "no reply")


# ----------------------------------------------------------------------------
class TestFormatting(unittest.TestCase):
    def test_success_line(self):
        r = ap.PingResult(TS, "8.8.8.8", True, 14)
        self.assertEqual(ap.format_result(r), "2026-10-24 13:55:01 | 8.8.8.8 |   14 ms")

    def test_failed_line(self):
        r = ap.PingResult(TS, "8.8.8.8", False, None, False, "timed out")
        self.assertEqual(ap.format_result(r),
                         "2026-10-24 13:55:01 | 8.8.8.8 |   -- ms | FAILED PING (timed out)")

    def test_slow_line_has_time_and_failed(self):
        r = ap.PingResult(TS, "h", False, 2350, False, "exceeded 2 s limit")
        line = ap.format_result(r)
        self.assertIn("2350 ms", line)
        self.assertIn("FAILED PING", line)

    def test_target_padding(self):
        r = ap.PingResult(TS, "a", True, 1)
        self.assertEqual(ap.format_result(r, 5).split(" | ")[1], "a    ")


# ----------------------------------------------------------------------------
class TestConfig(TempDirTest):
    def test_valid(self):
        cfg = ap.load_config(write_config(self.tmp))
        self.assertEqual(cfg.targets, ["127.0.0.1"])
        self.assertEqual(cfg.log_file_path, (self.tmp / "logs" / "test.log").resolve())
        self.assertEqual(cfg.max_log_bytes, 1024 * 1024)
        self.assertEqual(cfg.log_mode, "all")

    def test_shipped_config_is_valid(self):
        cfg = ap.load_config(ROOT / "config.json")
        self.assertGreaterEqual(len(cfg.targets), 1)

    def test_single_string_target(self):
        cfg = ap.load_config(write_config(self.tmp, targets="example.com"))
        self.assertEqual(cfg.targets, ["example.com"])

    def test_log_mode_default_and_case(self):
        p = write_config(self.tmp)
        data = json.loads(p.read_text())
        del data["log_mode"]
        p.write_text(json.dumps(data))
        self.assertEqual(ap.load_config(p).log_mode, "all")
        self.assertEqual(ap.load_config(write_config(self.tmp, log_mode="FAILURES")).log_mode, "failures")

    def test_utf8_bom_accepted(self):
        # Notepad on older Windows saves UTF-8 with a BOM.
        p = write_config(self.tmp)
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        ap.load_config(p)

    def test_absolute_log_path(self):
        target = self.tmp / "elsewhere" / "x.log"
        cfg = ap.load_config(write_config(self.tmp, log_file_path=str(target)))
        self.assertEqual(cfg.log_file_path, target)

    def test_invalid_values(self):
        bad = [
            {"targets": []},
            {"targets": [""]},
            {"targets": ["-t"]},
            {"targets": ["two words"]},
            {"targets": ["https://example.com"]},
            {"targets": [5]},
            {"interval_seconds": 0},
            {"interval_seconds": "5"},
            {"timeout_seconds": -1},
            {"timeout_seconds": True},
            {"max_log_size_mb": 0},
            {"log_file_count": 0},
            {"log_file_count": 2.5},
            {"log_file_path": ""},
            {"log_mode": "some"},
        ]
        for override in bad:
            with self.subTest(override=override):
                with self.assertRaises(ap.ConfigError):
                    ap.load_config(write_config(self.tmp, **override))

    def test_missing_key(self):
        p = write_config(self.tmp)
        data = json.loads(p.read_text())
        del data["timeout_seconds"]
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ap.ConfigError, "timeout_seconds"):
            ap.load_config(p)

    def test_bad_json_mentions_backslashes(self):
        p = self.tmp / "config.json"
        p.write_text('{"log_file_path": "C:\\Logs\\x.log"}')  # single backslashes = invalid JSON
        with self.assertRaisesRegex(ap.ConfigError, "backslash"):
            ap.load_config(p)

    def test_missing_file(self):
        with self.assertRaises(ap.ConfigError):
            ap.load_config(self.tmp / "nope.json")


# ----------------------------------------------------------------------------
class TestRotatingLog(TempDirTest):
    def make(self, count, max_bytes=200):
        return ap.RotatingLog(self.tmp / "logs" / "p.log", max_bytes, count, warn=lambda m: None)

    def test_creates_folder(self):
        log = self.make(3)
        log.write("hello")
        self.assertTrue((self.tmp / "logs" / "p.log").is_file())

    def test_size_limit_and_file_count(self):
        log = self.make(3, max_bytes=200)
        for i in range(200):
            log.write(f"line {i:04d} " + "x" * 30)
        files = sorted(p.name for p in (self.tmp / "logs").iterdir())
        self.assertEqual(files, ["p.1.log", "p.2.log", "p.log"])
        for p in (self.tmp / "logs").iterdir():
            self.assertLessEqual(p.stat().st_size, 200)
        # Newest entry in the current file, older entries in the numbered files.
        self.assertIn("line 0199", (self.tmp / "logs" / "p.log").read_text())
        newest_backup = (self.tmp / "logs" / "p.1.log").read_text()
        oldest_backup = (self.tmp / "logs" / "p.2.log").read_text()
        self.assertGreater(newest_backup, oldest_backup)
        self.assertNotIn("line 0000", "".join(p.read_text() for p in (self.tmp / "logs").iterdir()))

    def test_single_file_mode_restarts_file(self):
        log = self.make(1, max_bytes=100)
        for i in range(50):
            log.write(f"line {i:04d} xxxxxxxx")
        self.assertEqual([p.name for p in (self.tmp / "logs").iterdir()], ["p.log"])
        self.assertLessEqual((self.tmp / "logs" / "p.log").stat().st_size, 100)

    def test_prunes_files_when_count_lowered(self):
        folder = self.tmp / "logs"
        folder.mkdir()
        for name in ["p.log", "p.1.log", "p.2.log", "p.3.log", "p.4.log", "other.log", "p.x.log"]:
            (folder / name).write_text("data")
        self.make(2)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["other.log", "p.1.log", "p.log", "p.x.log"])

    def test_write_failure_does_not_crash(self):
        warnings = []
        log = ap.RotatingLog(self.tmp / "p.log", 1000, 2, warn=warnings.append)
        with mock.patch("builtins.open", side_effect=PermissionError("locked")):
            log.write("x")
        self.assertTrue(warnings)

    def test_existing_files_order(self):
        log = self.make(5, max_bytes=30)
        for i in range(10):
            log.write(f"entry {i}")
        names = [p.name for p in log.existing_files()]
        self.assertEqual(names[0], "p.log")
        self.assertEqual(names[1:], sorted(names[1:], key=lambda n: int(n.split(".")[1])))


# ----------------------------------------------------------------------------
class TestCycle(TempDirTest):
    def fake_ping(self, target, timeout):
        if target == "bad":
            return ap.PingResult(TS, target, False, None, False, "timed out")
        return ap.PingResult(TS, target, True, 5)

    def run_mode(self, mode):
        cfg = ap.load_config(write_config(self.tmp, targets=["good", "bad"], log_mode=mode))
        log = ap.RotatingLog(cfg.log_file_path, cfg.max_log_bytes, cfg.log_file_count)
        printed = []
        with ThreadPoolExecutor(2) as ex:
            results = ap.run_cycle(cfg, log, ex, ping_func=self.fake_ping, out=printed.append)
        return results, printed, cfg.log_file_path.read_text().splitlines()

    def test_all_mode_logs_everything_in_order(self):
        results, printed, lines = self.run_mode("all")
        self.assertEqual([r.target for r in results], ["good", "bad"])
        self.assertEqual(len(printed), 2)
        self.assertEqual(lines, printed)
        self.assertIn("FAILED PING", lines[1])

    def test_failures_mode_logs_only_failures(self):
        _, printed, lines = self.run_mode("failures")
        self.assertEqual(len(printed), 2)          # console still shows every ping
        self.assertEqual(len(lines), 1)
        self.assertIn("bad", lines[0])
        self.assertIn("FAILED PING", lines[0])


# ----------------------------------------------------------------------------
class TestMain(TempDirTest):
    def test_once_with_mocked_ping(self):
        cfg_path = write_config(self.tmp, targets=["good"])
        out = io.StringIO()
        with mock.patch.object(ap, "ping", lambda t, s: ap.PingResult(datetime.now(), t, True, 3)), \
                redirect_stdout(out):
            code = ap.main(["--config", str(cfg_path), "--once"])
        self.assertEqual(code, 0)
        lines = (self.tmp / "logs" / "test.log").read_text().splitlines()
        self.assertTrue(lines[0].startswith("# ") and "session started" in lines[0])
        self.assertIn("good |    3 ms", lines[1])
        self.assertIn("session stopped", lines[-1])

    def test_bad_config_exit_code(self):
        cfg_path = write_config(self.tmp, interval_seconds=-5)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = ap.main(["--config", str(cfg_path), "--once"])
        self.assertEqual(code, 2)
        self.assertIn("interval_seconds", err.getvalue())

    def test_missing_ping_command(self):
        cfg_path = write_config(self.tmp)
        with mock.patch.object(ap.subprocess, "run", side_effect=FileNotFoundError), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = ap.main(["--config", str(cfg_path), "--once"])
        self.assertEqual(code, 4)
        self.assertIn("ping", err.getvalue())

    def test_ping_process_hang_is_failure(self):
        with mock.patch.object(ap.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("ping", 1)):
            r = ap.ping("h", 1)
        self.assertFalse(r.success)

    def test_ping_uses_subprocess_output(self):
        fake = subprocess.CompletedProcess(["ping"], 0, stdout=WIN_SUCCESS)
        with mock.patch.object(ap.subprocess, "run", return_value=fake) as run:
            r = ap.ping("8.8.8.8", 2)
        self.assertTrue(r.success)
        self.assertEqual(r.rtt_ms, 14)
        self.assertNotIn("shell", run.call_args.kwargs)


# ----------------------------------------------------------------------------
@unittest.skipUnless(shutil.which("ping"), "system ping command not available")
class TestRealPing(TempDirTest):
    """Runs the script exactly as a user would, against the local machine."""

    def run_script(self, *extra, **overrides):
        cfg_path = write_config(self.tmp, **overrides)
        return subprocess.run(
            [sys.executable, str(ROOT / "auto_pinger.py"), "--config", str(cfg_path), *extra],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def test_localhost_and_unresolvable_host(self):
        proc = self.run_script("--once", targets=["127.0.0.1", "nothing.invalid"], timeout_seconds=2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[0], ap.BANNER)
        log = (self.tmp / "logs" / "test.log").read_text(encoding="utf-8").splitlines()
        local = next(l for l in log if "127.0.0.1" in l and not l.startswith("#"))
        invalid = next(l for l in log if "nothing.invalid" in l and not l.startswith("#"))
        self.assertNotIn("FAILED PING", local, local)
        self.assertRegex(local, r"\d ms")
        self.assertIn("FAILED PING", invalid)

    def test_interval_loop_and_ctrl_c_free_stop(self):
        # Run the real loop for a few cycles, then terminate the process.
        cfg_path = write_config(self.tmp, interval_seconds=1)
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "auto_pinger.py"), "--config", str(cfg_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            import time
            time.sleep(3.5)
        finally:
            proc.kill()
            proc.wait(10)
        lines = [l for l in (self.tmp / "logs" / "test.log").read_text().splitlines()
                 if not l.startswith("#")]
        self.assertGreaterEqual(len(lines), 3)
        self.assertLessEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
