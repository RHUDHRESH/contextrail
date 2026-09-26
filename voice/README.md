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
| `POST /v1/queries` `{question, channel, actor_external_id \| null}` → `Answer {text, run_id, citations}` | `answer_query` | implemented in engine HTTP door |
| `POST /v1/identities/resolve` `{channel, external_id}` → `{person_id, display_name}` or 404 | `resolve_actor` | implemented in engine HTTP door |
| `POST /v1/approvals/pending` `{channel, actor_external_id}` → `{runs: [RunView]}` (runs with a row awaiting that person) | reads `RunView` | implemented in engine HTTP door |
| `POST /v1/voice/requests` `{request_text, actor_external_id, source_ref}` → `{run, ticket}` | `start_run` + catalog request | one attempt per call; ticket spoken only after read-back verification |

Phone numbers travel in request bodies, never in URLs, so they stay out of access logs (CLAUDE.md §16). Unknown
callers send `actor_external_id: null` to `/v1/queries`.

Vobiz's documented callback signature covers only the URL and nonce, not `From`, `CallUUID`, or `Digits` in the
POST form. The voice edge therefore treats every live caller as unknown, disables phone approval decisions and
paid transfer, and rejects repeated nonces within its single process. Registered caller status, ticket creation,
approvals, and transfer require a provider-side call lookup that independently verifies the caller and call ID;
they are not enabled by merely setting `VOBIZ_AUTH_TOKEN`. The nonce cache is per process and is not a shared
replay store across replicas.

The phone request uses the Vobiz `CallUUID` as `source_ref` only after caller verification is implemented. The engine persists an attempt before the
Freshservice catalog POST, so a timed-out or crashed request is never blindly posted again. `ticket.status` is
`verified`, `unverified`, `unknown`, `attempted`, or `blocked`; the phone names the ticket only for `verified`.
The catalog item and tenant access must be configured for a LIVE ticket. Otherwise the result is explicitly
FIXTURE or blocked. The DTMF and transfer flows are implemented but disabled on the live HTTP edge pending
provider-side call verification. High-risk approvals stay in Slack or Teams. The XML follows Vobiz's
[voice XML guidance](https://github.com/vobiz-ai/Agent-Skills/blob/main/skills/vobiz-voice-xml/SKILL.md).

**Tests** are offline: Sarvam, Vobiz, the model and the engine are all faked.

```bash
uv venv --python D:/AIWorkspace/Python/cpython-3.12-windows-x86_64-none/python.exe voice/.venv
uv pip install --python voice/.venv/Scripts/python.exe -r voice/requirements-dev.txt
cd voice && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider && .venv/Scripts/ruff.exe check .
```
