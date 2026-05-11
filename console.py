"""Console bootstrap helpers for opening a TRex node through a CML terminal server.

Local dependencies:
- Python 3 standard library only
- ``ssh`` available on the local machine

Remote node dependencies:
- ``tmux``
- ``python3``
- TRex installed and reachable under ``/trex`` with the bundled interactive
  control-plane modules available

Security note:
- No connection target, username, or password is hardcoded in this module.
- Callers must pass host, user, lab, node, and credential information
  explicitly, either as arguments or environment variables.
"""

from __future__ import annotations

import errno
import getpass
import json
import os
import pty
import re
import select
import shlex
import sys
import termios
import time
import tty
from collections.abc import Sequence
from dataclasses import dataclass


TMUX_PREFIX = b"\x02"  # Ctrl-b
DETACH_ESCAPE = b"\x1d"  # Ctrl-]
PROMPT_RE = re.compile(r"[^\n]*# ")
TREX_PROMPT_RE = re.compile(r"trex(?:\(read-only\))?>")
ACQUIRE_FAILED_RE = re.compile(r"Failed to acquire all required ports", re.IGNORECASE)
BATCH_DONE_RE = re.compile(r"\[Done\]")
BATCH_ERROR_RE = re.compile(r"\[FAILED\]|Traceback|error:", re.IGNORECASE)
PASSWORD_RE = re.compile(r"password:", re.IGNORECASE)
CONNECTED_RE = re.compile(r"Connected to CML terminalserver\.")
TMUX_STATUS_RE = re.compile(r"\[trex\]")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\([A-Za-z0-9]|\x0f|\r")

SERVER_WINDOW = "codex-trex-server"
CONSOLE_WINDOW = "codex-trex-console"

CONSOLE_PYTHON = (
    'import sys,types,shutil,runpy; '
    'dist=types.ModuleType("distutils"); '
    'spawn=types.ModuleType("distutils.spawn"); '
    'spawn.find_executable=shutil.which; '
    'dist.spawn=spawn; '
    'sys.modules["distutils"]=dist; '
    'sys.modules["distutils.spawn"]=spawn; '
    'sys.argv=["trex_console","-s","127.0.0.1"]; '
    'runpy.run_module("trex.console.trex_console", run_name="__main__")'
)


@dataclass(slots=True)
class TrexConsoleConfig:
    jump_host: str = ""
    user: str = ""
    lab_name: str = ""
    node_name: str = ""
    node_port: str = "0"
    console_path: str | None = None
    password_env: str = "TREXCMLLIB_PASSWORD"
    password: str | None = None
    connect_timeout: float = 30.0
    command_timeout: float = 20.0
    console_timeout: float = 40.0
    server_wait: float = 4.0
    server_mode: str = "stl"
    server_args: tuple[str, ...] | None = None
    server_workdir: str | None = None
    readonly: bool = True
    force_acquire: bool = False
    exit_after_prompt: bool = False

    def build_console_path(self) -> str:
        if self.console_path:
            return self.console_path
        missing = [name for name, value in (("lab_name", self.lab_name), ("node_name", self.node_name)) if not value]
        if missing:
            raise SessionError(f"missing required console path fields: {', '.join(missing)}")
        return f"/{self.lab_name}/{self.node_name}/{self.node_port}"


@dataclass(slots=True)
class TrexConsoleBatchResult:
    success: bool
    output: str
    batch_file: str


def _default_server_args(server_mode: str) -> list[str]:
    mode = server_mode.lower()
    if mode == "stl":
        return ["-i"]
    if mode == "astf":
        return ["-i", "--astf"]
    raise SessionError(f"unsupported TRex server mode: {server_mode}")


def _build_server_start_cmd(config: TrexConsoleConfig) -> str:
    explicit_server_args = list(config.server_args) if config.server_args is not None else None
    default_server_args = _default_server_args(config.server_mode)
    python_script = f"""
import json
import os
import re
import shlex
import signal
import subprocess
import time

SERVER_WINDOW = {SERVER_WINDOW!r}
server_mode = {config.server_mode!r}
explicit_args = json.loads({json.dumps(json.dumps(explicit_server_args))})
default_args = json.loads({json.dumps(json.dumps(default_server_args))})
explicit_workdir = {config.server_workdir!r}
binary = os.path.realpath('/trex/_t-rex-64-o')
ld_path = '/trex/so:/trex/so/x86_64:' + os.environ.get('LD_LIBRARY_PATH', '')
mode_flags = {{'--astf', '--no-scapy-server'}}

def resolve_workdir():
    if server_mode != 'astf':
        return '/trex'
    if explicit_workdir:
        return explicit_workdir
    roots = []
    for root in ('/trex', os.path.realpath('/trex')):
        if root and root not in roots and os.path.isdir(root):
            roots.append(root)
    for root in roots:
        for current_root, _, files in os.walk(root):
            if 'astf_schema.json' in files:
                return current_root
    return '/trex'

workdir = resolve_workdir()

def current_server():
    out = subprocess.run(['ps', '-ef'], capture_output=True, text=True, check=True).stdout.splitlines()
    pattern = re.compile(r'(?:(?:--\\s+)?)(?P<binary>/\\S*_t-rex-64-o)\\s*(?P<args>.*)$')
    for line in out:
        if '_t-rex-64-o' not in line or 'grep' in line:
            continue
        match = pattern.search(line)
        if not match:
            continue
        parts = line.split(None, 2)
        pid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        args = shlex.split(match.group('args'))
        return pid, os.path.realpath(match.group('binary')), args
    return None, None, None

def build_desired_args(current_args):
    if explicit_args is not None:
        return explicit_args
    if current_args:
        desired = [arg for arg in current_args if arg not in mode_flags]
        if '-i' not in desired:
            desired.insert(0, '-i')
    else:
        desired = list(default_args)
    if server_mode == 'astf':
        if '--astf' not in desired:
            desired.append('--astf')
    return desired

pid, current_binary, current_args = current_server()
desired_args = build_desired_args(current_args)

if pid and current_binary == binary and current_args == desired_args:
    print('__TREX_SERVER_ALREADY_RUNNING__')
    raise SystemExit(0)

if pid:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid = None
    else:
        for _ in range(20):
            time.sleep(0.25)
            if not os.path.exists(f'/proc/{{pid}}'):
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1.0)

subprocess.run(['tmux', 'kill-window', '-t', SERVER_WINDOW], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
launch_inner = (
    f'export LD_LIBRARY_PATH={{shlex.quote(ld_path)}}; '
    f'cd {{shlex.quote(workdir)}}; '
    + 'exec '
    + shlex.join([binary, *desired_args])
)
subprocess.run(['tmux', 'new-window', '-d', '-n', SERVER_WINDOW, launch_inner], check=True)
"""
    return "python3 - <<'PY'\n" + python_script.strip() + "\nPY"


def build_console_start_cmd(*, readonly: bool = False, force_acquire: bool = False) -> str:
    console_args = ["trex_console", "-s", "127.0.0.1"]
    if force_acquire:
        console_args.append("-f")
    elif readonly:
        console_args.append("-r")

    inner = (
        "cd /trex/automation/trex_control_plane/interactive && "
        "python -c "
        + shlex.quote(
            CONSOLE_PYTHON.replace(
                'sys.argv=["trex_console","-s","127.0.0.1"]',
                "sys.argv=" + repr(console_args),
            )
        )
    )
    return (
        f"tmux kill-window -t {CONSOLE_WINDOW} 2>/dev/null || true; "
        f"tmux new-window -n {CONSOLE_WINDOW} {shlex.quote(inner)}"
    )


class SessionError(RuntimeError):
    """Raised when the remote console does not reach the expected state."""


class PtySession:
    def __init__(self, argv: list[str]) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:
            os.execvp(argv[0], argv)

        self._pid = pid
        self._master_fd = master_fd
        self._returncode: int | None = None
        self._buffer = ""

    def close(self) -> None:
        try:
            os.close(self._master_fd)
        except OSError:
            pass

    def poll(self) -> int | None:
        if self._returncode is not None:
            return self._returncode

        pid, status = os.waitpid(self._pid, os.WNOHANG)
        if pid == 0:
            return None

        if os.WIFEXITED(status):
            self._returncode = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self._returncode = 128 + os.WTERMSIG(status)
        else:
            self._returncode = status

        return self._returncode

    def send_bytes(self, data: bytes) -> None:
        os.write(self._master_fd, data)

    def send_line(self, text: str) -> None:
        self.send_bytes(text.encode("utf-8") + b"\n")

    def clear_buffer(self) -> None:
        self._buffer = ""

    def _read_once(self, timeout: float) -> bytes:
        ready, _, _ = select.select([self._master_fd], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(self._master_fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return b""
            raise SessionError(f"failed reading remote console: {exc}") from exc

    def expect(
        self,
        patterns: list[re.Pattern[str]],
        timeout: float,
        *,
        echo: bool = True,
    ) -> int:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            chunk = self._read_once(remaining)
            if not chunk:
                rc = self.poll()
                if rc is not None:
                    raise SessionError(f"remote session exited early with code {rc}")
                continue

            if echo:
                os.write(sys.stdout.fileno(), chunk)

            decoded = chunk.decode("utf-8", errors="ignore")
            self._buffer += decoded
            self._buffer = self._buffer[-20000:]

            for idx, pattern in enumerate(patterns):
                if pattern.search(self._buffer):
                    return idx

        patterns_text = ", ".join(pattern.pattern for pattern in patterns)
        raise SessionError(f"timed out waiting for: {patterns_text}")

    def interact(self) -> None:
        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        old_attrs = termios.tcgetattr(stdin_fd)

        print("\nAttached to remote TRex console. Press Ctrl-] to exit.\n")
        tty.setraw(stdin_fd)

        try:
            while self.poll() is None:
                ready, _, _ = select.select([stdin_fd, self._master_fd], [], [])

                if self._master_fd in ready:
                    data = os.read(self._master_fd, 4096)
                    if not data:
                        break
                    os.write(stdout_fd, data)

                if stdin_fd in ready:
                    data = os.read(stdin_fd, 1024)
                    if not data:
                        break
                    if DETACH_ESCAPE in data:
                        break
                    os.write(self._master_fd, data)
        finally:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)


class TrexConsoleLauncher:
    """Open a remote TRex console through a CML host and land on ``trex>``."""

    def __init__(self, config: TrexConsoleConfig) -> None:
        self.config = config

    def get_password(self, password: str | None = None) -> str:
        if password:
            return password
        if self.config.password:
            return self.config.password

        env_password = os.environ.get(self.config.password_env)
        if env_password:
            return env_password

        prompt = f"Password for {self.config.user}@{self.config.jump_host}: "
        return getpass.getpass(prompt)

    def _open_shell_session(self, password: str | None = None) -> PtySession:
        cfg = self.config
        ssh_cmd = [
            "ssh",
            "-tt",
            f"{cfg.user}@{cfg.jump_host}",
            f"open {cfg.build_console_path()}",
        ]

        session = PtySession(ssh_cmd)
        idx = session.expect(
            [PASSWORD_RE, CONNECTED_RE, TMUX_STATUS_RE, PROMPT_RE],
            timeout=cfg.connect_timeout,
            echo=False,
        )

        if idx == 0:
            session.send_line(self.get_password(password))
            session.expect(
                [CONNECTED_RE, TMUX_STATUS_RE, PROMPT_RE],
                timeout=cfg.connect_timeout,
                echo=False,
            )

        session.send_bytes(TMUX_PREFIX + b"c")
        session.expect([PROMPT_RE], timeout=cfg.command_timeout, echo=False)
        return session

    def _ensure_server_running(self, session: PtySession) -> None:
        cfg = self.config
        session.send_line(_build_server_start_cmd(cfg))
        session.expect([PROMPT_RE], timeout=cfg.command_timeout, echo=False)
        time.sleep(cfg.server_wait)

    def ensure_server_running(self, *, password: str | None = None) -> None:
        session = self._open_shell_session(password=password)
        try:
            self._ensure_server_running(session)
        finally:
            session.close()

    @staticmethod
    def _clean_output(text: str) -> str:
        return ANSI_RE.sub("", text)

    def run_shell_commands(
        self,
        commands: Sequence[str],
        *,
        password: str | None = None,
        timeout: float | None = None,
    ) -> str:
        session = self._open_shell_session(password=password)
        wait_timeout = timeout or self.config.command_timeout
        try:
            session.clear_buffer()
            for command in commands:
                session.send_line(command)
                session.expect([PROMPT_RE], timeout=wait_timeout, echo=False)
            return self._clean_output(session._buffer)
        finally:
            session.close()

    def run_console_batch(
        self,
        commands: Sequence[str],
        *,
        password: str | None = None,
        ports: Sequence[int] | None = None,
        force_acquire: bool | None = None,
        readonly: bool | None = None,
        timeout: float | None = None,
    ) -> TrexConsoleBatchResult:
        cfg = self.config
        session = self._open_shell_session(password=password)
        batch_file = f"/tmp/codex_trex_batch_{int(time.time() * 1000)}.txt"
        timeout = timeout or cfg.console_timeout
        try:
            self._ensure_server_running(session)

            payload = "\n".join(commands).rstrip() + "\n"
            session.clear_buffer()
            session.send_line(f"cat > {batch_file} <<'EOF'\n{payload}EOF")
            session.expect([PROMPT_RE], timeout=cfg.command_timeout, echo=False)

            argv = ["trex_console", "-s", "127.0.0.1"]
            selected_ports = list(ports) if ports is not None else []
            if selected_ports:
                argv.extend(["-a", *[str(port) for port in selected_ports]])

            if force_acquire is None:
                force_acquire = cfg.force_acquire
            if readonly is None:
                readonly = cfg.readonly and not force_acquire

            if force_acquire:
                argv.append("-f")
            elif readonly:
                argv.append("-r")

            argv.extend(["--batch", batch_file])
            inner = (
                "cd /trex/automation/trex_control_plane/interactive && "
                "python -c "
                + shlex.quote(
                    CONSOLE_PYTHON.replace(
                        'sys.argv=["trex_console","-s","127.0.0.1"]',
                        "sys.argv=" + repr(argv),
                    )
                )
            )

            session.clear_buffer()
            session.send_line(inner)
            deadline = time.time() + timeout
            while time.time() < deadline:
                chunk = session._read_once(1.0)
                if chunk:
                    session._buffer += chunk.decode("utf-8", errors="ignore")
                    session._buffer = session._buffer[-50000:]
                if BATCH_DONE_RE.search(session._buffer):
                    break
                if BATCH_ERROR_RE.search(session._buffer) and TREX_PROMPT_RE.search(session._buffer):
                    break

            output = self._clean_output(session._buffer)
            success = bool(BATCH_DONE_RE.search(output)) and not bool(BATCH_ERROR_RE.search(output))

            # Exit the interactive console if it stayed open after the batch completed.
            session.send_bytes(b"\x03")
            try:
                session.expect([PROMPT_RE], timeout=cfg.command_timeout, echo=False)
            except SessionError:
                pass

            return TrexConsoleBatchResult(success=success, output=output, batch_file=batch_file)
        finally:
            session.close()

    def connect_and_bootstrap(
        self,
        password: str | None = None,
        *,
        interactive: bool | None = None,
    ) -> None:
        cfg = self.config
        interactive = (not cfg.exit_after_prompt) if interactive is None else interactive
        session = self._open_shell_session(password=password)
        try:
            self._ensure_server_running(session)

            session.clear_buffer()
            session.send_line(
                build_console_start_cmd(
                    readonly=cfg.readonly,
                    force_acquire=cfg.force_acquire,
                )
            )
            idx = session.expect(
                [TREX_PROMPT_RE, ACQUIRE_FAILED_RE],
                timeout=cfg.console_timeout,
            )

            if idx == 1 and not cfg.readonly and not cfg.force_acquire:
                print("\nPort acquisition failed; retrying in readonly mode.")
                session.clear_buffer()
                session.send_line(build_console_start_cmd(readonly=True))
                session.expect([TREX_PROMPT_RE], timeout=cfg.console_timeout)

            print("\nReached live trex> prompt.")
            if interactive:
                session.interact()
        finally:
            session.close()
