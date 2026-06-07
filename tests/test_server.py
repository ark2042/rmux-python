import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from librmux import RmuxCommandError, RmuxCompatibilityError, Server


class ServerTests(unittest.TestCase):
    def test_cmd_injects_socket_path_and_preserves_exit(self) -> None:
        with fake_rmux() as binary:
            server = Server(binary=binary, socket_path="/tmp/rmux.sock")

            run = server.cmd("list-sessions", "--json")

        self.assertEqual(run.returncode, 3)
        self.assertEqual(run.stderr, "fake stderr\n")
        self.assertEqual(
            run.stdout.splitlines(),
            ["-S", "/tmp/rmux.sock", "list-sessions", "--json"],
        )

    def test_checked_command_raises_with_run_attached(self) -> None:
        with fake_rmux() as binary:
            server = Server(binary=binary)

            with self.assertRaises(RmuxCommandError) as raised:
                server.cmd("list-sessions", check=True)

        self.assertEqual(raised.exception.run.returncode, 3)

    def test_json_methods_parse_objects_and_arrays(self) -> None:
        responses = {
            ("capabilities", "--json"): {
                "binary_contract_version": 1,
                "json_commands": ["list-sessions", "list-windows", "list-panes"],
            },
            ("list-sessions", "--json"): [{"session_name": "demo"}],
            ("list-windows", "-a", "--json"): [{"window_index": 0}],
            ("list-panes", "-t", "demo:0", "--json"): [{"pane_id": "%1"}],
            ("list-clients", "--json"): [],
        }
        with fake_rmux_json(responses) as binary:
            server = Server(binary=binary)

            self.assertEqual(server.capabilities()["binary_contract_version"], 1)
            self.assertEqual(server.list_sessions()[0]["session_name"], "demo")
            self.assertEqual(server.list_windows(all_sessions=True)[0]["window_index"], 0)
            self.assertEqual(server.list_panes(target="demo:0")[0]["pane_id"], "%1")
            self.assertEqual(server.list_clients(), [])

    def test_rejects_incompatible_binary_contract(self) -> None:
        responses = {
            ("capabilities", "--json"): {
                "binary_contract_version": 2,
                "json_commands": ["list-sessions"],
            },
        }
        with fake_rmux_json(responses) as binary:
            server = Server(binary=binary)

            with self.assertRaises(RmuxCompatibilityError):
                server.list_sessions()

    def test_can_skip_compatibility_check_for_alpha_targets(self) -> None:
        responses = {
            ("capabilities", "--json"): {
                "binary_contract_version": 2,
                "json_commands": [],
            },
            ("list-sessions", "--json"): [{"session_name": "demo"}],
        }
        with fake_rmux_json(responses) as binary:
            server = Server(binary=binary, check_compatibility=False)

            self.assertEqual(server.list_sessions()[0]["session_name"], "demo")
            self.assertEqual(server.capabilities()["binary_contract_version"], 2)

    def test_object_model_uses_thin_cli_targets(self) -> None:
        responses = {
            ("capabilities", "--json"): {
                "binary_contract_version": 1,
                "json_commands": ["list-sessions", "list-windows", "list-panes"],
            },
            ("list-sessions", "--json"): [{"session_name": "demo"}],
            ("list-windows", "-t", "demo", "--json"): [{"window_index": 0}],
            ("list-panes", "-t", "demo:0", "--json"): [
                {"pane_index": 0, "pane_id": "%4"}
            ],
            ("display-message", "--json", "-t", "%4", "#{pane_id}"): {
                "message": "%4"
            },
        }
        with fake_rmux_json(responses) as binary:
            server = Server(binary=binary)

            session = server.sessions()[0]
            pane = session.windows()[0].panes()[0]

            self.assertEqual(session.name, "demo")
            self.assertEqual(pane.target, "%4")
            self.assertEqual(
                server.display_message("#{pane_id}", target=pane.target)["message"],
                "%4",
            )

    def test_endpoint_selector_accepts_socket_name(self) -> None:
        with fake_rmux() as binary:
            server = Server(binary=binary, socket_name="demo")

            run = server.cmd("list-panes")

        self.assertEqual(run.stdout.splitlines()[:2], ["-L", "demo"])

    def test_rejects_ambiguous_endpoint_configuration(self) -> None:
        with self.assertRaises(ValueError):
            Server(socket_path="/tmp/rmux.sock", socket_name="demo")


class fake_rmux:
    def __enter__(self) -> str:
        self.root = tempfile.TemporaryDirectory()
        path = Path(self.root.name) / "rmux-fake"
        path.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do printf '%s\\n' \"$arg\"; done\n"
            "printf 'fake stderr\\n' >&2\n"
            "exit 3\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.path = path
        return str(path)

    def __exit__(self, exc_type, exc, tb) -> None:
        self.root.cleanup()


class fake_rmux_json:
    def __init__(self, responses) -> None:
        self.responses = responses

    def __enter__(self) -> str:
        self.root = tempfile.TemporaryDirectory()
        root = Path(self.root.name)
        data_path = root / "responses.json"
        data = {"\0".join(key): value for key, value in self.responses.items()}
        data_path.write_text(json.dumps(data), encoding="utf-8")
        path = root / "rmux-json"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "data = json.load(open(os.environ['RMUX_FAKE_RESPONSES'], encoding='utf-8'))\n"
            "key = '\\0'.join(sys.argv[1:])\n"
            "if key not in data:\n"
            "    print('missing fake response for ' + repr(sys.argv[1:]), file=sys.stderr)\n"
            "    sys.exit(2)\n"
            "print(json.dumps(data[key]))\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.previous = os.environ.get("RMUX_FAKE_RESPONSES")
        os.environ["RMUX_FAKE_RESPONSES"] = str(data_path)
        self.path = path
        return str(path)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.previous is None:
            os.environ.pop("RMUX_FAKE_RESPONSES", None)
        else:
            os.environ["RMUX_FAKE_RESPONSES"] = self.previous
        self.root.cleanup()


if __name__ == "__main__":
    unittest.main()
