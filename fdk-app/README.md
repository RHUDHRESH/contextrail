# ContextRail ticket sidebar (Freshservice)

The Freshservice ticket-sidebar app for ContextRail (CLAUDE.md §13.2). It shows, on the ticket itself, what the
rail decided for every action: ✅ ALLOW, 🟠 HOLD for a named approver, ⛔ REFUSE with the policy clause quoted.
It never decides anything and holds no secrets: it renders the engine's `RunView` and calls the engine only
through FDK request templates.

Platform 3.0 · FDK 10.x · Node 24.x · Crayons 4.x · module `service_ticket` · location `ticket_sidebar`.

## Features

- Ticket sidebar that loads the ContextRail run for the open ticket: status pill, LIVE/FIXTURE badge
  (LIVE only when every connector is LIVE), one row per action.
- Rows: ✅ ALLOW with a verified tick (only when the engine read it back), 🟠 HOLD with approver and deadline,
  ⛔ REFUSE struck through with the policy clause quoted.
- Empty state with **Run ContextRail on this ticket** when the ticket has no run yet.

## Engine contract

Every call goes through a request template in `config/requests.json` with
`Authorization: Bearer <engine_token>`; the host is the `engine_url` installation parameter.

| Template | Call | Expected answers |
|---|---|---|
| `getRunByTicket` | `GET /v1/runs/by-ticket/{ticket_id}` | 200 `RunView` JSON; 404 when the ticket has no run |
| `startRun` | `POST /v1/runs` | 200/201/202 `RunView`; 409 when the ticket already has a run |

`startRun` body (the same idempotency key from every trigger, so the engine keeps one run per ticket):

```json
{"ticket_id": 25, "source": "freshservice", "trigger": "fdk_sidebar", "idempotency_key": "freshservice:ticket:25"}
```

## Setup

1. Install the FDK CLI (FDK 10.x refuses to start unless Node is exactly 24.11.x):
   `npm install -g https://cdn.freshdev.io/fdk/latest-v24.tgz`.
2. From this folder: `npm install` (test harness only), then `fdk validate` and `fdk unit-test`.
   `fdk validate` exits 0 even when it lists errors: read the summary table, not the exit code.
3. `fdk run` and open a Freshservice ticket with `?dev=true`.

## Usage

Open any ticket in Freshservice; the ContextRail panel appears in the ticket sidebar.
