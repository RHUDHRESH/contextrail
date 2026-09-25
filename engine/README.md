# engine/

The ContextRail engine: Python 3.12, FastAPI, port 8000. This is the only service that decides or writes to
external systems. It holds the eight-stage rail, the policy engine, the LLM router, connectors (LIVE/FIXTURE),
the door contract (`contextrail/surfaces/door.py`) and the hash-chained audit. See CLAUDE.md §4–§13.
