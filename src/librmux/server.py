"""Subprocess-backed RMUX client."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping


JsonObject = dict[str, Any]


class RmuxCommandError(RuntimeError):
    """Raised when an rmux command exits unsuccessfully through a checked API."""

    def __init__(self, run: "CommandRun") -> None:
        message = run.stderr.strip() or f"rmux exited with status {run.returncode}"
        super().__init__(message)
        self.run = run


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


class Server:
    """Thin wrapper around the ``rmux`` binary.

    The wrapper never invokes a shell. Endpoint selectors are injected before
    command arguments so every method talks to the intended daemon.
    """

    def __init__(
        self,
        *,
        binary: str | Path = "rmux",
        socket_path: str | Path | None = None,
        socket_name: str | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        if socket_path is not None and socket_name is not None:
            raise ValueError("choose only one of socket_path or socket_name")
        self.binary = str(binary)
        self.socket_path = None if socket_path is None else str(socket_path)
        self.socket_name = socket_name
        self.env = None if env is None else dict(env)
        self.cwd = None if cwd is None else str(cwd)

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

        value = self._json_object("capabilities", "--json")
        return value

    def list_sessions(self) -> list[JsonObject]:
        """Return ``rmux list-sessions --json``."""

        return self._json_list("list-sessions", "--json")

    def list_windows(
        self, *, target: str | None = None, all_sessions: bool = False
    ) -> list[JsonObject]:
        """Return ``rmux list-windows --json``."""

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

        args: list[object] = ["list-panes"]
        if all_sessions:
            args.append("-a")
        if target is not None:
            args.extend(["-t", target])
        args.append("--json")
        return self._json_list(*args)

    def list_clients(self, *, target_session: str | None = None) -> list[JsonObject]:
        """Return ``rmux list-clients --json``."""

        args: list[object] = ["list-clients"]
        if target_session is not None:
            args.extend(["-t", target_session])
        args.append("--json")
        return self._json_list(*args)

    def send_keys(self, target: str, *keys: object) -> CommandRun:
        """Send key tokens or text to a pane target."""

        return self.cmd("send-keys", "-t", target, *keys, check=True)

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

        return subprocess.Popen(
            self._argv(["-C"]),
            cwd=self.cwd,
            env=self._merged_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

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
        return dict(self.env)
