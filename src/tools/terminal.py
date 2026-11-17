import sys
import os
import uuid
import time
import base64
import queue
import atexit
import logging
import threading
import subprocess
from typing import Callable, Optional
from src.tools.fast_launcher import execute_fast_command

logger = logging.getLogger(__name__)

# Global callback for notifying UI of active tool execution
_activity_callback: Optional[Callable[[str], None]] = None

def set_activity_callback(callback: Optional[Callable[[str], None]]):
    global _activity_callback
    _activity_callback = callback

def notify_activity(action_text: str):
    if _activity_callback:
        try:
            _activity_callback(action_text)
        except Exception as e:
            logger.warning(f"[Tools] Error in activity callback: {e}")

BLOCKED_PATTERNS = [
    "format c:",
    "del /f /s /q c:\\windows",
    "rmdir /s /q c:\\windows",
    "remove-item -recurse -force c:\\windows",
    "shutdown /s /t 0"
]

class PowerShellSession:
    """
    Long-lived background PowerShell daemon process with bidirectional piped stdin/stdout.
    Drops execution latency from ~900ms to 3-20ms per command and preserves environment state.
    Uses unique sentinel markers to delimit command outputs cleanly and safely.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.process: Optional[subprocess.Popen] = None
        self._queue: queue.Queue = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._is_ready = False
        self._start_process()

    def _start_process(self):
        if sys.platform != "win32":
            return

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            self.process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NoLogo",
                    "-NonInteractive",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", "-"
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                startupinfo=startupinfo
            )

            self._queue = queue.Queue()
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()

            # Warm up UTF-8 encoding in the session
            init_cmd = (
                "$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "[Console]::InputEncoding = [System.Text.Encoding]::UTF8\n"
            )
            self.process.stdin.write(init_cmd)
            self.process.stdin.flush()
            self._is_ready = True
            logger.info("[PowerShellSession] Warm PowerShell daemon successfully initialized.")
        except Exception as e:
            logger.error(f"[PowerShellSession] Failed to initialize warm PowerShell daemon: {e}")
            self.process = None
            self._is_ready = False

    def _reader_loop(self):
        proc = self.process
        if not proc or not proc.stdout:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                self._queue.put(line)
        except Exception:
            pass

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def execute(self, command: str, timeout: float = 30.0) -> str:
        with self._lock:
            if not self.is_alive():
                logger.info("[PowerShellSession] Process not running, restarting daemon...")
                self._start_process()
                if not self.is_alive():
                    raise RuntimeError("Could not start PowerShell daemon process.")

            # Drain any stale leftover lines from previous timeout/crash
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            marker = f"__SENTINEL_{uuid.uuid4().hex}__"
            # Encode command in Base64 and execute via dot-sourced ScriptBlock with try/catch/finally.
            # This completely avoids any syntax escaping issues (trailing comments, quotes, newlines,
            # here-strings) and guarantees the sentinel is always printed in finally even on terminating errors.
            b64_cmd = base64.b64encode(command.encode("utf-8")).decode("ascii")
            wrapped_cmd = (
                f". {{ try {{ . ([ScriptBlock]::Create([System.Text.Encoding]::UTF8.GetString("
                f"[System.Convert]::FromBase64String('{b64_cmd}')))) }} "
                f"catch {{ Write-Output $_ }} finally {{ [Console]::Out.WriteLine('{marker}') }} }}\n"
            )

            try:
                self.process.stdin.write(wrapped_cmd)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                logger.warning(f"[PowerShellSession] Broken pipe on write, restarting daemon: {e}")
                self._start_process()
                raise e

            lines = []
            start_t = time.time()
            while True:
                remaining = timeout - (time.time() - start_t)
                if remaining <= 0:
                    logger.warning(f"[PowerShellSession] Command execution timed out ({timeout}s): '{command}'")
                    self._restart_after_timeout()
                    return f"⚠️ Ошибка: выполнение команды превысило лимит времени ({int(timeout)} секунд): '{command}'"

                try:
                    line = self._queue.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    if not self.is_alive():
                        logger.warning("[PowerShellSession] Process exited unexpectedly during execution.")
                        break
                    continue

                stripped = line.rstrip("\r\n")
                if marker in stripped:
                    # Output complete
                    break
                lines.append(stripped)

            output = "\n".join(lines).strip()
            return output if output else "[Команда выполнена успешно, вывод пуст]"

    def _restart_after_timeout(self):
        try:
            if self.process:
                self.process.kill()
        except Exception:
            pass
        self._start_process()

    def close(self):
        with self._lock:
            if self.process:
                try:
                    self.process.stdin.write("exit\n")
                    self.process.stdin.flush()
                    self.process.terminate()
                except Exception:
                    pass
                self.process = None

# Global warm PowerShell session instance
_ps_daemon_session: Optional[PowerShellSession] = None
_session_lock = threading.Lock()

def get_powershell_session() -> PowerShellSession:
    global _ps_daemon_session
    if _ps_daemon_session is None:
        with _session_lock:
            if _ps_daemon_session is None:
                _ps_daemon_session = PowerShellSession()
    return _ps_daemon_session

@atexit.register
def _cleanup_powershell_session():
    global _ps_daemon_session
    if _ps_daemon_session:
        try:
            _ps_daemon_session.close()
        except Exception:
            pass
        _ps_daemon_session = None

def _run_subprocess_fallback(command: str) -> str:
    """Fallback execution path using standard subprocess.run."""
    ps_command = f"$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"
    process = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
        capture_output=True,
        timeout=30
    )

    stdout = ""
    stderr = ""
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            if process.stdout and not stdout:
                stdout = process.stdout.decode(enc)
            if process.stderr and not stderr:
                stderr = process.stderr.decode(enc)
        except UnicodeDecodeError:
            continue

    if not stdout and process.stdout:
        stdout = process.stdout.decode("utf-8", errors="replace")
    if not stderr and process.stderr:
        stderr = process.stderr.decode("utf-8", errors="replace")

    output = stdout.strip()
    if stderr.strip():
        output += f"\n[stderr / Ошибки]:\n{stderr.strip()}"
    if not output:
        output = f"[Команда выполнена успешно с кодом возврата {process.returncode}, вывод пуст]"
    return output

def run_terminal_command(command: str) -> str:
    """Выполняет команду в консоли Windows PowerShell и возвращает консольный вывод.
    Используется для:
    - Просмотра файлов, папок, поиска информации на дисках (dir, Get-ChildItem, findstr).
    - Диагностики процессов, памяти, процессора (Get-Process, tasklist, wmic).
    - Сетевой диагностики (ping, ipconfig, netstat, curl, test-netconnection).
    - Запуска и проверки скриптов, утилит (python, pip, git, node).
    
    Args:
        command: Точная строка команды для выполнения в PowerShell.
    Returns:
        Текст ответа консоли (stdout, ошибки, код возврата).
    """
    cmd_lower = command.lower().strip()
    for blocked in BLOCKED_PATTERNS:
        if blocked in cmd_lower:
            return f"❌ Ошибка безопасности: выполнение потенциально опасной команды '{command}' заблокировано."

    logger.info(f"[TerminalTool] Executing command: {command}")
    notify_activity(f"⚙️ Выполняю в консоли: {command}")

    # 1. Check for instant fast launch (2-5ms instead of 800ms PowerShell startup)
    fast_result = execute_fast_command(command)
    if fast_result is not None:
        return fast_result

    # 2. Execute via warm PowerShell daemon session (3-20ms)
    try:
        session = get_powershell_session()
        output = session.execute(command, timeout=30.0)
    except Exception as e:
        logger.warning(f"[TerminalTool] PowerShell daemon error, falling back to subprocess: {e}")
        try:
            output = _run_subprocess_fallback(command)
        except subprocess.TimeoutExpired:
            return f"⚠️ Ошибка: выполнение команды превысило лимит времени (30 секунд): '{command}'"
        except Exception as e2:
            logger.error(f"[TerminalTool] Subprocess fallback error: {e2}")
            return f"❌ Ошибка выполнения команды: {e2}"

    # Truncate if output is excessively long (e.g. > 4000 chars) to prevent context overflow
    if len(output) > 4000:
        output = output[:4000] + "\n...[вывод обрезан из-за большого объема]..."

    return output
