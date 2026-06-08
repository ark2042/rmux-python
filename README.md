# librmux

`librmux` is the Python SDK for RMUX. Its public handles follow the same
vocabulary as the Rust SDK: `Rmux`, `Session`, `Window`, and `Pane`.

```python
from librmux import Rmux

rmux = Rmux()
for session in rmux.list_sessions():
    print(session["session_name"])
```

`Server` remains available as an alias for existing code.

## Endpoint Selection

```python
Rmux()                         # default rmux endpoint
Rmux(socket_path="/tmp/rmux")   # passes -S /tmp/rmux
Rmux(socket_name="demo")        # passes -L demo
Rmux.builder().socket_name("demo").connect_or_start()
```

## Common Operations

```python
session = rmux.ensure_session("demo")
pane = session.pane(0, 0)
pane.send_text("echo hello\n")
pane.expect_visible_text().to_contain("hello").timeout(5)
text = pane.capture_text()
```

For raw commands:

```python
run = rmux.cmd("rename-window", "-t", "demo:0", "logs")
if run.returncode != 0:
    raise RuntimeError(run.stderr)
```
