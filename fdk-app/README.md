# ContextRail ticket sidebar (Freshservice)

The Freshservice ticket-sidebar app for ContextRail (CLAUDE.md §13.2). It shows, on the ticket itself, what the
rail decided for every action: ✅ ALLOW, 🟠 HOLD for a named approver, ⛔ REFUSE with the policy clause quoted.
It never decides anything and holds no secrets: it renders the engine's `RunView` and calls the engine only
through FDK request templates.

Platform 3.0 · FDK 10.x · Node 24.x · Crayons 4.x · module `service_ticket` · location `ticket_sidebar`.

## Features

- Ticket sidebar that loads the ContextRail run for the open ticket.

## Setup

1. Install the FDK CLI (FDK 10.x refuses to start unless Node is exactly 24.11.x):
   `npm install -g https://cdn.freshdev.io/fdk/latest-v24.tgz`.
2. From this folder: `npm install` (test harness only), then `fdk validate` and `fdk unit-test`.
   `fdk validate` exits 0 even when it lists errors: read the summary table, not the exit code.
3. `fdk run` and open a Freshservice ticket with `?dev=true`.

## Usage

Open any ticket in Freshservice; the ContextRail panel appears in the ticket sidebar.
