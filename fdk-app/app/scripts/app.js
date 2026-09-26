// Sidebar controller: reads the open ticket, fetches its ContextRail run through the request templates and renders
// it with CRView. It holds no secrets and makes no decisions; the engine is the only source of every verdict.
(function () {
  const V = window.CRView;
  const state = { client: null, ticketId: null };
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
      showEngineError(err);
    }
  }

  function render(view) {
    document.getElementById('cr-status').replaceChildren(V.renderHeader(document, view));
    document.getElementById('cr-body').replaceChildren();
  }

  function ticketIdOf(data) {
    const id = data && data.ticket ? data.ticket.id : null;
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  function showEngineError(err) {
    const status = err && err.status;
    const text = ENGINE_ERRORS.get(status) ||
      'The ContextRail engine returned an error (HTTP ' + (status || 'unknown') + '). Reload the ticket to try again.';
    showMessage('error', text);
  }

  function showMessage(type, text) {
    const message = V.el(document, 'fw-inline-message', { type: type, closable: 'false' }, text);
    document.getElementById('cr-body').replaceChildren(message);
  }
})();
