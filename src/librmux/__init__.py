"""Python SDK for RMUX."""

__version__ = "0.6.0"

from .builder import RmuxBuilder
from .handles import Pane, Session, Window
from .server import (
    CommandRun,
    RMUX,
    Rmux,
    RmuxCommandError,
    RmuxCompatibilityError,
    Server,
)
from .expectations import TextExpectation, TextMatch
from .control import (
    ControlEvent,
    ControlExit,
    ControlExtendedOutput,
    ControlModeClient,
    ControlNotification,
    ControlOutput,
)
from .lifecycle import PaneExitState
from .locators import LocatorExpectation, TextLocator
from .pane_set import PaneSet, PaneSetExpectation, PaneSetOutcome
from .snapshots import PaneSnapshot
from .streams import PaneLineStream, PaneOutputChunk, PaneOutputStream, PaneRenderStream
from .trace import RmuxTraceBuilder, TraceSession

__all__ = [
    "CommandRun",
    "ControlEvent",
    "ControlExit",
    "ControlExtendedOutput",
    "ControlModeClient",
    "ControlNotification",
    "ControlOutput",
    "LocatorExpectation",
    "Pane",
    "PaneExitState",
    "PaneLineStream",
    "PaneOutputChunk",
    "PaneOutputStream",
    "PaneRenderStream",
    "PaneSet",
    "PaneSetExpectation",
    "PaneSetOutcome",
    "PaneSnapshot",
    "RMUX",
    "Rmux",
    "RmuxBuilder",
    "RmuxCommandError",
    "RmuxCompatibilityError",
    "Server",
    "Session",
    "TextExpectation",
    "TextLocator",
    "TextMatch",
    "RmuxTraceBuilder",
    "TraceSession",
    "Window",
    "__version__",
]
