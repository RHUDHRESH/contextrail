# voice/

The voice door: an inbound and outbound conversational agent over a Vobiz phone number with Sarvam
Saaras STT, Sarvam-105B Conversations and Bulbul TTS. It is based on
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
POST form. With both `VOBIZ_AUTH_ID` and `VOBIZ_AUTH_TOKEN`, the answer handler performs an authenticated
`GET /api/v1/Account/{auth_id}/Call/{call_uuid}/?status=live` read-back and requires exact call ID, caller,
destination, inbound direction, and in-progress status. Any mismatch or API error leaves the caller unknown.
Without both credentials, only general policy questions work. Phone approval decisions and paid transfer remain
disabled because subsequent callback form fields are also unsigned. Repeated nonces are rejected within the
single voice process; this cache is not shared across replicas.

The phone request uses the provider-verified Vobiz `CallUUID` as `source_ref`. The engine persists an attempt before the
Freshservice catalog POST, so a timed-out or crashed request is never blindly posted again. `ticket.status` is
`verified`, `unverified`, `unknown`, `attempted`, or `blocked`; the phone names the ticket only for `verified`.
The catalog item and tenant access must be configured for a LIVE ticket. Otherwise the result is explicitly
FIXTURE or blocked. The DTMF and transfer flows are implemented but disabled on the live HTTP edge pending
body-bound callback authentication. High-risk approvals stay in Slack or Teams. The XML follows Vobiz's
[voice XML guidance](https://github.com/vobiz-ai/Agent-Skills/blob/main/skills/vobiz-voice-xml/SKILL.md).

**Tests** are offline: Sarvam, Vobiz, the model and the engine are all faked.

For one live outbound test, run the deployed voice service at a public HTTPS
`VOICE_PUBLIC_URL` such as `https://your-host/voice`. It must report `LIVE`
Vobiz callbacks, Sarvam speech, Sarvam dialogue, and a configured engine at
`GET /health`. Then use the one-shot CLI; without `--dial` it checks the live
service and your owned caller ID but places no call:

```bash
python voice/make_call.py --to +919999999999 --voice-base https://your-host/voice
python voice/make_call.py --to +919999999999 --voice-base https://your-host/voice --dial
```

The CLI validates an active voice-capable number on the Vobiz account and
submits a single call to Vobiz. A timeout is an unknown outcome: inspect Vobiz
call history before considering another attempt. The voice conversation never
calls Anthropic; the engine can use Anthropic separately for workflow work.

```bash
uv venv --python D:/AIWorkspace/Python/cpython-3.12-windows-x86_64-none/python.exe voice/.venv
uv pip install --python voice/.venv/Scripts/python.exe -r voice/requirements-dev.txt
cd voice && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider && .venv/Scripts/ruff.exe check .
```
