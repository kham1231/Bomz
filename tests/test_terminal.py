import time
import unittest
from src.tools.terminal import run_terminal_command, get_powershell_session, PowerShellSession

class TestTerminalTool(unittest.TestCase):
    def test_run_command_echo(self):
        output = run_terminal_command("echo HelloBomzh")
        self.assertIn("HelloBomzh", output)

    def test_run_command_security_block(self):
        output = run_terminal_command("format c:")
        self.assertIn("заблокировано", output)

    def test_powershell_session_direct(self):
        session = get_powershell_session()
        self.assertTrue(session.is_alive())
        out = session.execute("Write-Output 'daemon_active'")
        self.assertIn("daemon_active", out)

    def test_powershell_session_state_persistence(self):
        session = get_powershell_session()
        session.execute("$session_test_val = 42")
        out = session.execute("$session_test_val * 2")
        self.assertIn("84", out)

    def test_powershell_session_latency(self):
        session = get_powershell_session()
        t0 = time.time()
        out = session.execute("Write-Output 'speed_check'")
        elapsed_ms = (time.time() - t0) * 1000
        self.assertIn("speed_check", out)
        # Should execute in less than 200ms (standard warm session is ~20ms, vs 800-1200ms cold start)
        self.assertLess(elapsed_ms, 250)

    def test_powershell_session_error_capture(self):
        session = get_powershell_session()
        out = session.execute("Get-Item non_existent_item_bomzh_xyz_12345")
        # PowerShell error stream merged into output
        self.assertTrue(len(out) > 0)
        self.assertTrue("Cannot find path" in out or "не удается найти путь" in out or "ObjectNotFound" in out or "non_existent_item" in out)

    def test_powershell_session_trailing_comment(self):
        session = get_powershell_session()
        t0 = time.time()
        out = session.execute("Get-Process -Name explorer # find active explorer process")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0)
        self.assertIn("explorer", out.lower())

    def test_powershell_session_terminating_error(self):
        session = get_powershell_session()
        t0 = time.time()
        out = session.execute("throw 'critical_terminating_failure'")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0)
        self.assertIn("critical_terminating_failure", out)

    def test_powershell_session_multiline_script(self):
        session = get_powershell_session()
        script = "$vals = 1..3\nforeach ($v in $vals) {\n    Write-Output \"val_$v\"\n}"
        out = session.execute(script)
        self.assertIn("val_1", out)
        self.assertIn("val_2", out)
        self.assertIn("val_3", out)

if __name__ == "__main__":
    unittest.main()
