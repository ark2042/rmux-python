"""Python handles for driving RMUX."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

from .control import ControlModeClient
from .handles import Pane, Session, Window


BINARY_CONTRACT_VERSION = 1


JsonObject = dict[str, Any]


class RmuxCommandError(RuntimeError):
    """Raised when an rmux command exits unsuccessfully through a checked API."""

    def __init__(self, run: "CommandRun") -> None:
        message = run.stderr.strip() or f"rmux exited with status {run.returncode}"
        super().__init__(message)
        self.run = run


class RmuxCompatibilityError(RuntimeError):
    """Raised when the rmux binary does not match this client contract."""


@dataclass(frozen=True)
class CommandRun:
    """Captured result from one rmux process invocation."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def check_returncode(self) -> "CommandRun":
        """Return self when successful, otherwise raise ``RmuxCommandError``."""

        if self.returncode != 0:
            raise RmuxCommandError(self)
        return self


class Rmux:
    """Client for the ``rmux`` binary contract.

    This client never invokes a shell. Endpoint selectors are injected before
    command arguments so every method talks to the intended daemon.
    """

    @classmethod
    def builder(cls):
        """Return a builder for this client."""

        from .builder import RmuxBuilder

        return RmuxBuilder()

    def __init__(
        self,
        *,
        binary: str | Path = "rmux",
        socket_path: str | Path | None = None,
        socket_name: str | None = None,
        check_compatibility: bool = True,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        if socket_path is not None and socket_name is not None:
            raise ValueError("choose only one of socket_path or socket_name")
        self.binary = str(binary)
        self.socket_path = None if socket_path is None else str(socket_path)
        self.socket_name = socket_name
        self.check_compatibility = check_compatibility
        self.env = None if env is None else dict(env)
        self.cwd = None if cwd is None else str(cwd)
        self._capabilities: JsonObject | None = None

    def cmd(self, *args: object, check: bool = False) -> CommandRun:
        """Run an rmux command and return stdout, stderr, and exit status."""

        argv = self._argv(args)
        completed = subprocess.run(
            argv,
            capture_output=True,
            cwd=self.cwd,
            env=self._merged_env(),
            text=True,
            check=False,
        )
        run = CommandRun(
            args=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check:
            run.check_returncode()
        return run

    def capabilities(self) -> JsonObject:
        """Return ``rmux capabilities --json``."""

        if self._capabilities is None:
            self._capabilities = self._json_object("capabilities", "--json")
            if self.check_compatibility:
                self._validate_capabilities(self._capabilities)
        return dict(self._capabilities)

    def list_sessions(self) -> list[JsonObject]:
        """Return ``rmux list-sessions --json``."""

        self._ensure_compatible()
        return self._json_list("list-sessions", "--json")

    def sessions(self) -> list[Session]:
        """Return typed session handles."""

        return [
            Session(self, str(session["session_name"]))
            for session in self.list_sessions()
        ]

    def session(self, name: str) -> Session:
        """Return a session handle by name."""

        return Session(self, name)

    def ensure_session(
        self,
        name: str,
        *,
        detached: bool = True,
        shell_command: str | None = None,
    ) -> Session:
        """Return an existing session or create it."""

        run = self.cmd("has-session", "-t", name)
        if run.returncode != 0:
            args: list[object] = ["new-session"]
            if detached:
                args.append("-d")
            args.extend(["-s", name])
            if shell_command is not None:
                args.append(shell_command)
            self.cmd(*args, check=True)
        return Session(self, name)

    def list_windows(
        self, *, target: str | None = None, all_sessions: bool = False
    ) -> list[JsonObject]:
        """Return ``rmux list-windows --json``."""

        self._ensure_compatible()
        args: list[object] = ["list-windows"]
        if all_sessions:
            args.append("-a")
        if target is not None:
            args.extend(["-t", target])
        args.append("--json")
        return self._json_list(*args)

    def list_panes(
        self, *, target: str | None = None, all_sessions: bool = False
    ) -> list[JsonObject]:
        """Return ``rmux list-panes --json``."""

        self._ensure_compatible()
        args: list[object] = ["list-panes"]
        if all_sessions:
            args.append("-a")
        if target is not None:
            args.extend(["-t", target])
        args.append("--json")
        return self._json_list(*args)

    def list_clients(self, *, target_session: str | None = None) -> list[JsonObject]:
        """Return ``rmux list-clients --json``."""

        self._ensure_compatible()
        args: list[object] = ["list-clients"]
        if target_session is not None:
            args.extend(["-t", target_session])
        args.append("--json")
        return self._json_list(*args)

    def send_keys(self, target: str, *keys: object) -> CommandRun:
        """Send key tokens or text to a pane target."""

        return self.cmd("send-keys", "-t", target, *keys, check=True)

    def send_text(self, target: str, text: str) -> CommandRun:
        """Send literal text to a pane target."""

        return self.cmd("send-keys", "-t", target, "-l", text, check=True)

    def display_message(
        self, message: str, *, target: str | None = None
    ) -> JsonObject:
        """Return ``display-message --json`` for one message or format."""

        self._ensure_compatible()
        args: list[object] = ["display-message", "--json"]
        if target is not None:
            args.extend(["-t", target])
        args.append(message)
        return self._json_object(*args)

    def capture_pane(
        self,
        *,
        target: str | None = None,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> str:
        """Return ``capture-pane -p`` text for a pane."""

        args: list[object] = ["capture-pane", "-p"]
        if target is not None:
            args.extend(["-t", target])
        if start is not None:
            args.extend(["-S", start])
        if end is not None:
            args.extend(["-E", end])
        if escape_ansi:
            args.append("-e")
        if join_wrapped:
            args.append("-J")
        return self.cmd(*args, check=True).stdout

    def control_mode(self) -> subprocess.Popen[str]:
        """Open ``rmux -C`` and return the live subprocess."""

        self._ensure_compatible()
        return subprocess.Popen(
            self._argv(["-C"]),
            cwd=self.cwd,
            env=self._merged_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def control(self) -> ControlModeClient:
        """Open a parsed control-mode client."""

        return ControlModeClient(self.control_mode())

    def pane_set(self, panes):
        """Create an ordered pane set."""

        from .pane_set import PaneSet

        return PaneSet(panes)

    def broadcast_text(self, panes, text: str):
        """Send literal text to every pane."""

        return self.pane_set(panes).broadcast_text(text)

    def broadcast_key(self, panes, key: str):
        """Send one key token to every pane."""

        return self.pane_set(panes).broadcast_key(key)

    def tracing(self):
        """Start building an in-memory trace session."""

        from .trace import RmuxTraceBuilder

        return RmuxTraceBuilder()

    def _json_list(self, *args: object) -> list[JsonObject]:
        value = self._json_value(*args)
        if not isinstance(value, list):
            raise TypeError("rmux JSON response is not an array")
        return value

    def _json_object(self, *args: object) -> JsonObject:
        value = self._json_value(*args)
        if not isinstance(value, dict):
            raise TypeError("rmux JSON response is not an object")
        return value

    def _json_value(self, *args: object) -> Any:
        run = self.cmd(*args, check=True)
        try:
            return json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"rmux returned invalid JSON: {exc}") from exc

    def _ensure_compatible(self) -> None:
        if self.check_compatibility:
            self.capabilities()

    def _validate_capabilities(self, capabilities: JsonObject) -> None:
        version = capabilities.get("binary_contract_version")
        if version != BINARY_CONTRACT_VERSION:
            raise RmuxCompatibilityError(
                "unsupported rmux binary contract version "
                f"{version!r}; expected {BINARY_CONTRACT_VERSION}"
            )

        commands = capabilities.get("json_commands")
        if not isinstance(commands, list) or "list-sessions" not in commands:
            raise RmuxCompatibilityError("rmux binary does not advertise JSON list commands")

    def _argv(self, args: Iterable[object]) -> list[str]:
        argv = [self.binary]
        if self.socket_name is not None:
            argv.extend(["-L", self.socket_name])
        if self.socket_path is not None:
            argv.extend(["-S", self.socket_path])
        argv.extend(str(arg) for arg in args)
        return argv

    def _merged_env(self) -> MutableMapping[str, str] | None:
        if self.env is None:
            return None
        env = dict(os.environ)
        env.update(self.env)
        return env


Server = Rmux
