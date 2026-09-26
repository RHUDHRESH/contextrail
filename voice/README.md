# voice/

The voice door: an inbound conversational agent over a Vobiz phone number with Sarvam STT/TTS. It is based on
`vobiz-ai/Vobiz-Sarvam` and runs on Python 3.12, because it needs `audioop`. It never decides anything; it calls
the engine's door contract. See CLAUDE.md §13.3.

**Source.** `agent.py` and `server.py` started as verbatim copies of `vobiz-ai/Vobiz-Sarvam` at commit
`ad44f49` (MIT). Attribution and the upstream licence text are in [`NOTICE`](NOTICE).

**Tests** are offline: Sarvam, Vobiz, the model and the engine are all faked.

```bash
uv venv --python D:/AIWorkspace/Python/cpython-3.12-windows-x86_64-none/python.exe voice/.venv
uv pip install --python voice/.venv/Scripts/python.exe -r voice/requirements-dev.txt
cd voice && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider && .venv/Scripts/ruff.exe check .
```
