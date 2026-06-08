"""Python handles for driving RMUX."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

from .expectations import (
    Duration,
    TextExpectation,
    TextMatch,
    duration_seconds,
    row_column,
)


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


@dataclass(frozen=True)
class Session:
    """A session target backed by an ``Rmux`` client."""

    server: "Rmux"
    name: str

    def list_windows(self) -> list[JsonObject]:
        """Return windows in this session."""

        return self.server.list_windows(target=self.name)

    def windows(self) -> list["Window"]:
        """Return typed window handles for this session."""

        return [
            Window(self.server, self.name, int(window["window_index"]))
            for window in self.list_windows()
        ]

    def window(self, index: int) -> "Window":
        """Return a window handle by index."""

        return Window(self.server, self.name, index)

    def pane(self, window_index: int = 0, pane_index: int = 0) -> "Pane":
        """Return a pane handle by window and pane index."""

        return self.window(window_index).pane(pane_index)


@dataclass(frozen=True)
class Window:
    """A window target backed by an ``Rmux`` client."""

    server: "Rmux"
    session_name: str
    index: int

    @property
    def target(self) -> str:
        """Return the window target string."""

        return f"{self.session_name}:{self.index}"

    def list_panes(self) -> list[JsonObject]:
        """Return panes in this window."""

        return self.server.list_panes(target=self.target)

    def panes(self) -> list["Pane"]:
        """Return typed pane handles for this window."""

        panes: list[Pane] = []
        for pane in self.list_panes():
            pane_id = pane.get("pane_id")
            if isinstance(pane_id, str) and pane_id:
                target = pane_id
            else:
                target = f"{self.target}.{int(pane['pane_index'])}"
            panes.append(Pane(self.server, target))
        return panes

    def pane(self, index: int) -> "Pane":
        """Return a pane handle by index."""

        return Pane(self.server, f"{self.target}.{index}")


@dataclass(frozen=True)
class Pane:
    """A pane target backed by an ``Rmux`` client."""

    server: "Rmux"
    target: str

    def send_keys(self, *keys: object) -> CommandRun:
        """Send key tokens or text to this pane."""

        return self.server.send_keys(self.target, *keys)

    def send_text(self, text: str) -> CommandRun:
        """Send literal text to this pane."""

        return self.server.send_text(self.target, text)

    def capture(
        self,
        *,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> str:
        """Return ``capture-pane -p`` text for this pane."""

        return self.server.capture_pane(
            target=self.target,
            start=start,
            end=end,
            escape_ansi=escape_ansi,
            join_wrapped=join_wrapped,
        )

    def capture_text(
        self,
        *,
        start: int | str | None = None,
        end: int | str | None = None,
        escape_ansi: bool = False,
        join_wrapped: bool = False,
    ) -> str:
        """Return visible text captured from this pane."""

        return self.capture(
            start=start,
            end=end,
            escape_ansi=escape_ansi,
            join_wrapped=join_wrapped,
        )

    def wait_for_text(
        self,
        text: str,
        *,
        timeout: Duration = 5.0,
        interval: Duration = 0.05,
    ) -> TextMatch:
        """Wait until captured pane text contains ``text``."""

        return self._wait_for_text(text, exact=False, timeout=timeout, interval=interval)

    def wait_for_exact_text(
        self,
        text: str,
        *,
        timeout: Duration = 5.0,
        interval: Duration = 0.05,
    ) -> TextMatch:
        """Wait until captured pane text equals ``text`` after trimming trailing newlines."""

        return self._wait_for_text(text, exact=True, timeout=timeout, interval=interval)

    def expect_visible_text(self) -> TextExpectation:
        """Create a text expectation for this pane."""

        return TextExpectation(self)

    def _wait_for_text(
        self,
        text: str,
        *,
        exact: bool,
        timeout: Duration,
        interval: Duration,
    ) -> TextMatch:
        timeout_seconds = duration_seconds(timeout)
        interval_seconds = duration_seconds(interval)
        deadline = time.monotonic() + timeout_seconds
        while True:
            captured = self.capture_text()
            if exact:
                if captured.rstrip("\n") == text:
                    return TextMatch(text=text, row=0, column=0)
            else:
                index = captured.find(text)
                if index >= 0:
                    row, column = row_column(captured, index)
                    return TextMatch(text=text, row=row, column=column)
            if time.monotonic() >= deadline:
                raise AssertionError(f"text not found before timeout: {text!r}")
            time.sleep(interval_seconds)


class Rmux:
    """Client for the ``rmux`` binary contract.

    This client never invokes a shell. Endpoint selectors are injected before
    command arguments so every method talks to the intended daemon.
    """

    @classmethod
    def builder(cls) -> "RmuxBuilder":
        """Return a builder for this client."""

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
        return dict(self.env)


class RmuxBuilder:
    """Builder for ``Rmux`` clients."""

    def __init__(self) -> None:
        self._binary: str | Path = "rmux"
        self._socket_path: str | Path | None = None
        self._socket_name: str | None = None
        self._check_compatibility = True
        self._env: Mapping[str, str] | None = None
        self._cwd: str | Path | None = None

    def binary(self, value: str | Path) -> "RmuxBuilder":
        """Use a specific rmux binary."""

        self._binary = value
        return self

    def socket_path(self, value: str | Path) -> "RmuxBuilder":
        """Use a specific socket path."""

        self._socket_path = value
        self._socket_name = None
        return self

    def socket_name(self, value: str) -> "RmuxBuilder":
        """Use a named socket."""

        self._socket_name = value
        self._socket_path = None
        return self

    def check_compatibility(self, enabled: bool) -> "RmuxBuilder":
        """Enable or disable the binary contract guard."""

        self._check_compatibility = enabled
        return self

    def env(self, value: Mapping[str, str] | None) -> "RmuxBuilder":
        """Set the environment used for rmux commands."""

        self._env = None if value is None else dict(value)
        return self

    def cwd(self, value: str | Path | None) -> "RmuxBuilder":
        """Set the working directory used for rmux commands."""

        self._cwd = value
        return self

    def connect_or_start(self) -> Rmux:
        """Build an ``Rmux`` client."""

        return Rmux(
            binary=self._binary,
            socket_path=self._socket_path,
            socket_name=self._socket_name,
            check_compatibility=self._check_compatibility,
            env=self._env,
            cwd=self._cwd,
        )


Server = Rmux
