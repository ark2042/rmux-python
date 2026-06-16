import json
import os
import stat
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from librmux import (
    ControlOutput,
    Pane,
    PaneSet,
    RMUX,
    Rmux,
    RmuxCommandError,
    RmuxCompatibilityError,
    Server,
    __version__,
)
from librmux.control import decode_tmux_octal, parse_control_line


class ServerTests(unittest.TestCase):
    def test_legacy_aliases_point_to_canonical_rmux_client(self) -> None:
        self.assertIs(RMUX, Rmux)
        self.assertIs(Server, Rmux)
        self.assertEqual(__version__, "0.6.0")

    def test_builder_creates_configured_client(self) -> None:
        with fake_rmux() as binary:
            rmux = (
                Rmux.builder()
                .binary(binary)
                .socket_name("demo")
                .check_compatibility(False)
                .connect_or_start()
            )

            run = rmux.cmd("list-panes")

        self.assertEqual(run.stdout.splitlines()[:2], ["-L", "demo"])

    def test_connect_or_start_validates_contract_when_enabled(self) -> None:
        responses = {
            ("start-server",): "",
            ("capabilities", "--json"): {
                "binary_contract_version": 1,
                "json_commands": ["list-sessions"],
            },
        }
        with fake_rmux_json(responses) as binary:
            rmux = Rmux.builder().binary(binary).connect_or_start()

            capabilities = rmux.capabilities()

        self.assertEqual(capabilities["binary_contract_version"], 1)

    def test_connect_or_start_starts_real_rmux_for_empty_socket(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = (
                Rmux.builder()
                .binary(binary)
                .socket_path(socket_path)
                .check_compatibility(False)
                .connect_or_start()
            )
            try:
                run = rmux.cmd("list-sessions", "--json")
            finally:
                rmux.cmd("kill-server")

        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), [])

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

    def test_custom_env_is_merged_with_process_environment(self) -> None:
        with fake_rmux_env() as binary:
            server = Server(binary=binary, env={"FOO": "bar"})

            run = server.cmd("env-check")

        self.assertIn("FOO=bar\n", run.stdout)
        self.assertRegex(run.stdout, r"PATH=.+")

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

    def test_object_model_uses_cli_targets(self) -> None:
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

    def test_session_returns_direct_pane_handle(self) -> None:
        responses = {
            ("capabilities", "--json"): {
                "binary_contract_version": 1,
                "json_commands": ["list-panes"],
            },
            ("list-panes", "-t", "demo:0", "--json"): [
                {"pane_index": 0, "pane_id": "%4"}
            ],
        }
        with fake_rmux_json(responses) as binary:
            session = Rmux(binary=binary).session("demo")

            pane = session.pane(0, 0)

        self.assertEqual(pane.target, "demo:0.0")

    def test_ensure_session_reuses_existing_session(self) -> None:
        responses = {
            ("has-session", "-t", "demo"): "",
        }
        with fake_rmux_json(responses) as binary:
            rmux = Rmux(binary=binary, check_compatibility=False)

            session = rmux.ensure_session("demo")

        self.assertEqual(session.name, "demo")

    def test_pane_text_helpers_use_literal_send_and_capture_polling(self) -> None:
        responses = {
            ("send-keys", "-t", "%4", "-l", "hello\n"): "",
            ("capture-pane", "-p", "-t", "%4"): "noise Ready\n",
        }
        with fake_rmux_json(responses) as binary:
            rmux = Rmux(binary=binary, check_compatibility=False)
            pane = Pane(rmux, "%4")

            run = pane.send_text("hello\n")
            match = pane.expect_visible_text().to_contain("Ready").timeout(
                timedelta(seconds=0.1)
            )

        self.assertEqual(run.returncode, 0)
        self.assertEqual(match.row, 0)
        self.assertEqual(match.column, 6)

    def test_control_output_parser_decodes_tmux_octal_bytes(self) -> None:
        event = parse_control_line(r"%output %4 hello world\012\134\377")

        self.assertIsInstance(event, ControlOutput)
        assert isinstance(event, ControlOutput)
        self.assertEqual(event.pane_id, "%4")
        self.assertEqual(event.data, b"hello world\n\\\xff")
        self.assertEqual(decode_tmux_octal(r"a\000b"), b"a\0b")

    def test_snapshot_and_text_locator_helpers(self) -> None:
        responses = {
            ("capture-pane", "-p", "-t", "%4"): "alpha Ready\nbeta Ready\n",
        }
        with fake_rmux_json(responses) as binary:
            rmux = Rmux(binary=binary, check_compatibility=False)
            pane = Pane(rmux, "%4")

            snapshot = pane.snapshot()
            first = pane.get_by_text("Ready").first().expect().to_be_visible().timeout(
                timedelta(seconds=0.1)
            )
            last = pane.locator("Ready").last().expect().to_have_text("Ready").timeout(
                timedelta(seconds=0.1)
            )
            count = pane.get_by_text("Ready").expect().to_have_count(2).timeout(
                timedelta(seconds=0.1)
            )

        self.assertEqual(snapshot.visible_text, "alpha Ready\nbeta Ready\n")
        self.assertEqual(snapshot.lines, ("alpha Ready", "beta Ready"))
        self.assertEqual(snapshot.row_text(1), "beta Ready")
        self.assertEqual(len(snapshot.find_all_text("Ready")), 2)
        self.assertEqual((first.row, first.column), (0, 6))
        self.assertEqual((last.row, last.column), (1, 5))
        self.assertEqual(count, 2)

    def test_pane_text_helpers_work_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session("py_sdk_smoke", shell_command="cat")
                pane = session.pane(0, 0)

                pane.send_text("hello-sdk\n")
                match = pane.expect_visible_text().to_contain("hello-sdk").timeout(3)
                located = pane.get_by_text("hello-sdk").expect().to_be_visible().timeout(
                    3
                )
                count = pane.get_by_text("hello-sdk").expect().to_have_count(2).timeout(
                    3
                )
                snapshot = pane.snapshot()
            finally:
                rmux.cmd("kill-server")

        self.assertEqual(match.text, "hello-sdk")
        self.assertEqual(match.row, 0)
        self.assertEqual(match.column, 0)
        self.assertEqual(located.text, "hello-sdk")
        self.assertEqual(count, 2)
        self.assertIn("hello-sdk", snapshot.visible_text)

    def test_pane_streams_work_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session("py_sdk_stream", shell_command="cat")
                pane = session.pane(0, 0)
                self.assertRegex(pane.id() or "", r"^%[0-9]+$")

                with pane.line_stream() as lines:
                    pane.send_text("stream sdk with spaces\n")
                    self.assertEqual(lines.next(timeout=3), "stream sdk with spaces")

                with pane.render_stream() as renders:
                    pane.send_text("render sdk with spaces\n")
                    snapshot = renders.next(timeout=3)
            finally:
                rmux.cmd("kill-server")

        self.assertIn("render sdk with spaces", snapshot.visible_text)

    def test_output_stream_preserves_spaces_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session("py_sdk_stream_spaces", shell_command="cat")
                pane = session.pane(0, 0)

                with pane.output_stream() as output:
                    pane.send_text("hello world\n")
                    chunk = output.next(timeout=3)
            finally:
                rmux.cmd("kill-server")

        self.assertIn(b"hello world", chunk.data)

    def test_wait_for_exit_works_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session(
                    "py_sdk_exit",
                    shell_command='sh -c "exit 7"',
                )
                state = session.pane(0, 0).wait_for_exit(timeout=3)
            finally:
                rmux.cmd("kill-server")

        self.assertTrue(state.dead)
        self.assertEqual(state.status, 7)

    def test_wait_for_exit_propagates_display_message_failures(self) -> None:
        with fake_rmux() as binary:
            rmux = Rmux(binary=binary, check_compatibility=False)
            pane = Pane(rmux, "%404")

            with self.assertRaises(RmuxCommandError):
                pane.wait_for_exit(timeout=0)

    def test_mutating_handles_work_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session("py_sdk_mutate", shell_command="cat")
                renamed = session.rename("py_sdk_mutate_renamed")
                window = renamed.window(0)

                window.rename("main")
                split = window.pane(0).split(direction="horizontal", shell_command="cat")
                split.select()
                split.resize(width=20)
                split.send_text("mutate-sdk\n")
                split.expect_visible_text().to_contain("mutate-sdk").timeout(3)
                window.select_layout("even-horizontal")
                extra = renamed.new_window(name="extra", shell_command="cat")
                extra.rename("logs")

                windows = renamed.list_windows()
                panes = window.list_panes()
            finally:
                rmux.cmd("kill-server")

        self.assertTrue(any(window["window_name"] == "main" for window in windows))
        self.assertTrue(any(window["window_name"] == "logs" for window in windows))
        self.assertGreaterEqual(len(panes), 2)

    def test_paneset_and_tracing_work_against_real_rmux(self) -> None:
        binary = real_rmux_binary()
        if binary is None:
            self.skipTest("real rmux binary not available")
        with tempfile.TemporaryDirectory() as root:
            socket_path = str(Path(root) / "rmux.sock")
            rmux = Rmux(
                binary=binary,
                socket_path=socket_path,
                check_compatibility=False,
            )
            rmux.cmd("kill-server")
            try:
                session = rmux.ensure_session("py_sdk_paneset", shell_command="cat")
                left = session.pane(0, 0)
                right = left.split(direction="horizontal", shell_command="cat")
                panes = PaneSet([left, right])

                panes.broadcast_text("paneset-sdk\n")
                outcome = panes.expect_all().visible_text_contains("paneset-sdk").timeout(
                    3
                )
                snapshots = panes.snapshot_all()
                trace = rmux.tracing().max_events(10).start()
                trace.record_action("broadcast paneset-sdk")
                trace.record_snapshot(left)
                trace_path = trace.stop(Path(root) / "trace")
            finally:
                rmux.cmd("kill-server")

            trace_lines = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(outcome.matched), 2)
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(all("paneset-sdk" in s.visible_text for s in snapshots))
        self.assertEqual(
            [event["kind"] for event in trace_lines],
            ["trace.start", "action", "snapshot", "trace.stop"],
        )

    def test_public_api_inventory_keeps_core_vocabulary_available(self) -> None:
        expected = {
            Rmux: [
                "builder",
                "cmd",
                "start_server",
                "ensure_session",
                "pane_set",
                "broadcast_text",
                "tracing",
            ],
            RMUX: [
                "builder",
                "cmd",
                "start_server",
                "ensure_session",
            ],
            Pane: [
                "snapshot",
                "get_by_text",
                "output_stream",
                "line_stream",
                "render_stream",
                "split",
                "resize",
                "wait_for_exit",
            ],
            PaneSet: ["broadcast_text", "snapshot_all", "expect_all", "expect_any"],
        }

        for cls, names in expected.items():
            for name in names:
                self.assertTrue(hasattr(cls, name), f"{cls.__name__}.{name} missing")

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
            "is_start=0\n"
            "for arg in \"$@\"; do [ \"$arg\" = start-server ] && is_start=1; done\n"
            "for arg in \"$@\"; do printf '%s\\n' \"$arg\"; done\n"
            "if [ \"$is_start\" = 1 ]; then exit 0; fi\n"
            "printf 'fake stderr\\n' >&2\n"
            "exit 3\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.path = path
        return str(path)

    def __exit__(self, exc_type, exc, tb) -> None:
        self.root.cleanup()


class fake_rmux_env:
    def __enter__(self) -> str:
        self.root = tempfile.TemporaryDirectory()
        path = Path(self.root.name) / "rmux-env"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "print('PATH=' + os.environ.get('PATH', ''))\n"
            "print('FOO=' + os.environ.get('FOO', ''))\n",
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
            "value = data[key]\n"
            "if isinstance(value, str):\n"
            "    print(value, end='')\n"
            "else:\n"
            "    print(json.dumps(value))\n",
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


def real_rmux_binary() -> str | None:
    configured = os.environ.get("RMUX_TEST_BINARY")
    if configured:
        path = Path(configured)
        return str(path) if path.exists() else None

    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "rmux" / "target" / "debug" / "rmux"
    return str(path) if path.exists() else None


if __name__ == "__main__":
    unittest.main()
