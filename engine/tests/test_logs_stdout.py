"""Log lines go to whatever stdout is when they are written, not the stream that existed at configure time.

Regression: configure_logging() pinned the stdout object of the moment. Under pytest that is a capture stream,
closed when its test ends, so the next warning anywhere in the suite raised "I/O operation on closed file".
"""

import io
import json
import sys

from contextrail.logs import configure_logging, get_logger


def test_logs_follow_stdout_after_it_is_replaced(monkeypatch):
    first, second = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", first)
    configure_logging("INFO", json=True)
    get_logger("t").warning("one")
    first.close()
    monkeypatch.setattr(sys, "stdout", second)
    get_logger("t").warning("two")  # used to raise ValueError: I/O operation on closed file
    assert json.loads(second.getvalue().splitlines()[-1])["event"] == "two"
