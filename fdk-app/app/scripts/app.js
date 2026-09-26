// Sidebar controller: reads the open ticket, fetches its ContextRail run through the request templates and renders
// it with CRView. It holds no secrets and makes no decisions; the engine is the only source of every verdict.
(function () {
  const V = window.CRView;
  // Poll only while the rail is actively moving. Held and ambiguous runs wait on people for hours, and the request
  // method is capped at 50 calls a minute per app per account, so those are refreshed on demand instead.
  const POLL_MS = 3000;
  const state = { client: null, ticketId: null, starting: false, timer: null };
  const TOKEN_REJECTED = 'The ContextRail engine rejected this app\'s credentials. Ask an admin to check the app settings.';
  const ENGINE_ERRORS = new Map([
    [401, TOKEN_REJECTED],
    [403, TOKEN_REJECTED],
    [429, 'Too many requests reached the ContextRail engine. Wait a minute, then reload the ticket.'],
    [504, 'The ContextRail engine did not answer in time. Reload the ticket to try again.']
  ]);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }

  async function start() {
    try {
      state.client = await app.initialized();
    } catch {
      showMessage('error', 'ContextRail could not start in this ticket. Reload the page to try again.');
      return;
    }
    await loadTicket();
  }

  async function loadTicket() {
    try {
      state.ticketId = ticketIdOf(await state.client.data.get('ticket'));
    } catch {
      showMessage('error', 'ContextRail could not read this ticket from Freshservice. Reload the page to try again.');
      return;
    }
    if (state.ticketId === null) {
      showMessage('error', 'This ticket has no numeric id, so ContextRail cannot look up its run.');
      return;
    }
    await refresh();
  }

  async function refresh() {
    try {
      const result = await state.client.request.invokeTemplate('getRunByTicket', {
        context: { ticket_id: state.ticketId }
      });
      render(JSON.parse(result.response));
    } catch (err) {
      if (err && err.status === 404) {
        showEmpty();
        return;
      }
      showMessage('error', engineErrorText(err));
    }
  }

  function showEmpty(errorText) {
    const box = V.renderEmpty(document, errorText);
    box.querySelector('#cr-run').addEventListener('fwClick', startRun);
    document.getElementById('cr-status').replaceChildren();
    document.getElementById('cr-body').replaceChildren(box);
  }

  // One start per click burst: the in-flight flag blocks a double click, and the engine dedupes on the
  // idempotency key in the body if another trigger got there first.
  async function startRun(event) {
    if (state.starting) {
      return;
    }
    state.starting = true;
    event.target.setAttribute('loading', '');
    event.target.setAttribute('disabled', '');
    try {
      const result = await state.client.request.invokeTemplate('startRun', {
        body: JSON.stringify(V.startRunBody(state.ticketId, 'fdk_sidebar'))
      });
      render(JSON.parse(result.response));
    } catch (err) {
      await afterFailedStart(err);
    } finally {
      state.starting = false;
    }
  }

  async function afterFailedStart(err) {
    if (err && err.status === 409) {
      await refresh();
      return;
    }
    showEmpty(engineErrorText(err));
  }

  function render(view) {
    document.getElementById('cr-status').replaceChildren(V.renderHeader(document, view));
    document.getElementById('cr-body').replaceChildren(V.renderRows(document, view));
    schedule(view);
  }

  // A chain of timeouts, each armed only after the previous answer arrived, so polls never overlap.
  function schedule(view) {
    clearTimeout(state.timer);
    state.timer = view.status === 'running' ? setTimeout(refresh, POLL_MS) : null;
  }

  function ticketIdOf(data) {
    const id = data && data.ticket ? data.ticket.id : null;
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  function engineErrorText(err) {
    const status = err && err.status;
    return ENGINE_ERRORS.get(status) ||
      'The ContextRail engine returned an error (HTTP ' + (status || 'unknown') + '). Reload the ticket to try again.';
  }

  function showMessage(type, text) {
    const message = V.el(document, 'fw-inline-message', { type: type, closable: 'false' }, text);
    document.getElementById('cr-body').replaceChildren(message);
  }
})();
