# voice/

The voice door: an inbound conversational agent over a Vobiz phone number with Sarvam STT/TTS. It is based on
`vobiz-ai/Vobiz-Sarvam` and runs on Python 3.12, because it needs `audioop`. It never decides anything; it calls
the engine's door contract. See CLAUDE.md §13.3.

**Source.** `agent.py` and `server.py` started as verbatim copies of `vobiz-ai/Vobiz-Sarvam` at commit
`ad44f49` (MIT). Attribution and the upstream licence text are in [`NOTICE`](NOTICE).

## Engine API

The voice door reaches ContextRail only through the engine's HTTP door (`engine_client.py`), with
`Authorization: Bearer $ENGINE_TOKEN` against `$ENGINE_URL` (compose sets `http://engine:8000`). Every call sends
`channel: "voice"` and, for a registered caller, `actor_external_id` = the caller's E.164 number, which the engine
maps through `identity_map.phone`. An empty or `change-me` token sends nothing.

| Call | Door function | Status |
|---|---|---|
| `POST /v1/runs` `{request_text, channel, actor_external_id, source_ref}` → `RunView` | `start_run` | matches `engine/contextrail/surfaces/rest.py` on `sec/P-platform` |
| `GET /v1/runs/{run_id}` → `RunView` | `get_status` | matches `sec/P-platform` |
| `POST /v1/runs/{run_id}/decisions` `{action_id, params_hash, channel, actor_external_id, decision, reason}` → `DecisionResult` | `decide` | matches `sec/P-platform` |
| `POST /v1/queries` `{question, channel, actor_external_id \| null}` → `Answer {text, run_id, citations}` | `answer_query` | **defined here; the engine must add it** |
| `POST /v1/identities/resolve` `{channel, external_id}` → `{person_id, display_name}` or 404 | `resolve_actor` | **defined here; the engine must add it** |
| `POST /v1/approvals/pending` `{channel, actor_external_id}` → `{runs: [RunView]}` (runs with a row awaiting that person) | reads `RunView` | **defined here; the engine must add it** |

Phone numbers travel in request bodies, never in URLs, so they stay out of access logs (CLAUDE.md §16). Unknown
callers send `actor_external_id: null` to `/v1/queries`.

**Tests** are offline: Sarvam, Vobiz, the model and the engine are all faked.

```bash
uv venv --python D:/AIWorkspace/Python/cpython-3.12-windows-x86_64-none/python.exe voice/.venv
uv pip install --python voice/.venv/Scripts/python.exe -r voice/requirements-dev.txt
cd voice && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider && .venv/Scripts/ruff.exe check .
```
