"""Builder for RMUX clients."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


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

    def connect_or_start(self):
        """Build a client, start the selected daemon, and validate the contract."""

        from .server import Rmux

        rmux = Rmux(
            binary=self._binary,
            socket_path=self._socket_path,
            socket_name=self._socket_name,
            check_compatibility=self._check_compatibility,
            env=self._env,
            cwd=self._cwd,
        )
        rmux.start_server()
        if self._check_compatibility:
            rmux.capabilities()
        return rmux
