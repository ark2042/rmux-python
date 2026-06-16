# librmux

`librmux` is the Python SDK for RMUX. Its public handles follow the same
vocabulary as the Rust SDK: `RMUX`, `Session`, `Window`, and `Pane`.

[Examples available](https://rmux.io/docs/examples/#/quickstart)

## Installation

```bash
python -m pip install librmux
```

`librmux` targets RMUX 0.6.0 and uses the `rmux` executable. Install the RMUX
binary separately and keep it on `PATH`, or pass a specific binary with
`RMUX.builder().binary(...)`.

```python
from librmux import RMUX

rmux = RMUX()
for session in rmux.list_sessions():
    print(session["session_name"])
```

`Rmux` and `Server` remain available as aliases for existing code.

## Endpoint Selection

```python
RMUX()                         # default rmux endpoint
RMUX(socket_path="/tmp/rmux")   # passes -S /tmp/rmux
RMUX(socket_name="demo")        # passes -L demo
RMUX.builder().socket_name("demo").connect_or_start()
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

## Publishing

This package is released to PyPI as `librmux` from version tags through
PyPI Trusted Publishing. Configure the PyPI project with workflow
`.github/workflows/release.yml` and environment `pypi`, then publish with:

```bash
git tag v0.6.0
git push origin v0.6.0
```
