# librmux

`librmux` is a thin Python SDK for RMUX. It uses the public `rmux` binary
contract: one-shot commands with `--json` and live control mode with `rmux -C`.

```python
from librmux import Server

server = Server()
for session in server.list_sessions():
    print(session["session_name"])
```

The wrapper does not use Rust FFI and does not speak the internal RMUX IPC
socket directly. The `rmux` binary owns endpoint resolution, daemon semantics,
and platform differences.

## Endpoint Selection

```python
Server()                         # default rmux endpoint
Server(socket_path="/tmp/rmux")   # passes -S /tmp/rmux
Server(socket_name="demo")        # passes -L demo
Server(check_compatibility=False) # skip the binary contract guard
```

## Common Operations

```python
server.capabilities()
server.list_sessions()
server.sessions()
server.list_windows(all_sessions=True)
server.list_panes(target="demo:0")
server.list_clients()
server.display_message("#{session_name}", target="demo:0.0")
server.send_keys("demo:0.0", "echo hello", "Enter")
text = server.capture_pane(target="demo:0.0")
```

For commands not yet modeled:

```python
run = server.cmd("rename-window", "-t", "demo:0", "logs")
if run.returncode != 0:
    raise RuntimeError(run.stderr)
```
