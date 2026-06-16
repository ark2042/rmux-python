"""Control-mode client and event parsing."""

from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Iterator

from .expectations import Duration, duration_seconds


@dataclass(frozen=True)
class ControlOutput:
    """Decoded `%output` pane bytes."""

    pane_id: str
    data: bytes


@dataclass(frozen=True)
class ControlExtendedOutput:
    """Decoded `%extended-output` pane bytes."""

    pane_id: str
    age_ms: int
    data: bytes


@dataclass(frozen=True)
class ControlExit:
    """Control-mode `%exit` event."""

    reason: str | None = None


@dataclass(frozen=True)
class ControlNotification:
    """Control-mode line that is not a pane-output payload."""

    prefix: str
    line: str


ControlEvent = (
    ControlOutput | ControlExtendedOutput | ControlExit | ControlNotification
)


class ControlModeClient:
    """Synchronous reader for `rmux -C`."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        if process.stdin is None or process.stdout is None:
            raise ValueError("control-mode process must expose stdin and stdout")
        self.process = process
        self._stdin = process.stdin
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="librmux-control-reader",
            daemon=True,
        )
        self._reader.start()

    def __enter__(self) -> "ControlModeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def send_command(self, command: str) -> None:
        """Send one command line to control mode."""

        if self.process.poll() is not None:
            raise RuntimeError("control-mode process has exited")
        self._stdin.write(command)
        if not command.endswith("\n"):
            self._stdin.write("\n")
        self._stdin.flush()

    def read_event(self, timeout: Duration | None = None) -> ControlEvent:
        """Read the next parsed control event."""

        timeout_seconds = None if timeout is None else duration_seconds(timeout)
        while True:
            try:
                line = self._lines.get(timeout=timeout_seconds)
            except queue.Empty as exc:
                raise TimeoutError("timed out waiting for control-mode event") from exc
            if line is None:
                raise EOFError("control-mode stream ended")
            event = parse_control_line(line.rstrip("\n"))
            if event is not None:
                return event

    def events(self, timeout: Duration | None = None) -> Iterator[ControlEvent]:
        """Yield parsed control events until EOF."""

        while True:
            try:
                event = self.read_event(timeout=timeout)
            except EOFError:
                return
            yield event
            if isinstance(event, ControlExit):
                return

    def wait_for_exit(self, timeout: Duration | None = None) -> ControlExit:
        """Read events until `%exit` is observed."""

        for event in self.events(timeout=timeout):
            if isinstance(event, ControlExit):
                return event
        raise EOFError("control-mode stream ended before %exit")

    def close(self) -> None:
        """Close stdin and wait for the control-mode process."""

        if self.process.poll() is None:
            try:
                self._stdin.write("\n")
                self._stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self._stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.process.stdout is not None:
            try:
                self.process.stdout.close()
            except OSError:
                pass
        if self.process.stderr is not None:
            try:
                self.process.stderr.close()
            except OSError:
                pass
        self._reader.join(timeout=2)

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)


def parse_control_line(line: str) -> ControlEvent | None:
    if not line.startswith("%"):
        return None
    if line.startswith("%output "):
        pane_id, payload = _split_payload(line[len("%output ") :])
        if pane_id is None:
            return ControlNotification("%output", line)
        return ControlOutput(pane_id, decode_tmux_octal(payload))
    if line.startswith("%extended-output "):
        pane_id, rest = _split_payload(line[len("%extended-output ") :])
        if pane_id is None:
            return ControlNotification("%extended-output", line)
        age, payload = _split_payload(rest)
        if age is None:
            return ControlNotification("%extended-output", line)
        if payload.startswith(": "):
            payload = payload[2:]
        try:
            age_ms = int(age)
        except ValueError:
            return ControlNotification("%extended-output", line)
        return ControlExtendedOutput(pane_id, age_ms, decode_tmux_octal(payload))
    prefix = line.split(" ", 1)[0]
    if prefix == "%exit":
        reason = line[len("%exit") :].strip()
        return ControlExit(reason or None)
    return ControlNotification(prefix, line)


def _split_payload(value: str) -> tuple[str | None, str]:
    head, separator, tail = value.partition(" ")
    if not head or not separator:
        return None, ""
    return head, tail


def decode_tmux_octal(value: str) -> bytes:
    output = bytearray()
    index = 0
    while index < len(value):
        if (
            value[index] == "\\"
            and index + 3 < len(value)
            and all("0" <= ch <= "7" for ch in value[index + 1 : index + 4])
        ):
            output.append(int(value[index + 1 : index + 4], 8))
            index += 4
        else:
            output.extend(value[index].encode("utf-8"))
            index += 1
    return bytes(output)
