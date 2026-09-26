# ContextRail: the user job

The primary user is an employee asking for an outcome: give someone access, start an onboarding workflow, fix an issue, or request help. They know **who** and **what should happen**; they should not need to know the rail, connector, agent, or policy vocabulary. A named approver has a separate, focused job: decide only the item assigned to them.

## Primary flow

1. Describe the outcome in one sentence.
2. Optionally **Add people**, **Add a workflow**, or **Ask someone to call**. These choices become part of the request. A call preference is not an outbound call.
3. Submit. Show a short status, what happens next, and any action the user must take.
4. Put evidence, policy clauses, agent handoffs, and the audit receipt behind **Details** for someone who needs to inspect them.

The smallest useful screen is one request box, the three optional additions, a submit button, and a short list of the user's requests. No metrics, connector inventory, or orchestration stages belong on that screen.

## Product boundary

The Python engine is the authority for identity, policy, named approvals, connector writes, and read-back verification. It may refuse a request or ask for a clearer person or action. The web interface must show that outcome without implying every request succeeded. The current Next.js interface uses fixture data and does **not** submit to the Python engine, create live Freshservice tickets, or place calls. Live voice requires a public callback, provider verification, and configured credentials; the call preference in the web demo does not supply these.

The development-only `/engine-demo` page is a separate local integration check. It submits to the running Python engine and shows its actual RunView, including connector modes. It currently seeds sample identities and entitlements; it is not a production access-change claim. The route is unavailable in production and accepts requests only through a local Next.js host and local engine URL.

Success for this redesign means a first-time user can prepare and submit a fixture request without understanding ContextRail internals, then find its status and next step. Technical details remain available on demand.
