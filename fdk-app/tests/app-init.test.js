/**
 * @vitest-environment jsdom
 */
// Client init: read the open ticket, fetch its run through the request template, render the header. Every
// failure on the way is shown to the agent (fw-review FF-04A), never swallowed.
import { boot, fakeClient, ok, fail, runView, bodyMessage } from './helpers/sidebar.js';

describe('sidebar init', () => {
  test('reads the open ticket and asks the engine for that ticket\'s run', async () => {
    const client = fakeClient({ engine: { getRunByTicket: () => ok(runView()) } });
    await boot(client);
    expect(client.data.get).toHaveBeenCalledWith('ticket');
    expect(client.request.invokeTemplate).toHaveBeenCalledWith('getRunByTicket', { context: { ticket_id: 25 } });
  });

  test('renders the status pill and the mode badge in the header', async () => {
    await boot(fakeClient({ engine: { getRunByTicket: () => ok(runView()) } }));
    expect(document.querySelector('#cr-status fw-pill').textContent).toBe('Running · Govern');
    expect(document.querySelector('#cr-status fw-label.cr-mode').getAttribute('value')).toBe('FIXTURE');
  });

  test('renders the run\'s verdict rows in the body', async () => {
    const rows = [
      { action_id: 'a1', label: 'Jira', verdict: 'ALLOW', state: 'verified', verified: true, rule_id: 'POL-ACC-001' },
      { action_id: 'a2', label: 'Prod admin', verdict: 'REFUSE', state: 'refused', verified: false, clause: 'No.' }
    ];
    await boot(fakeClient({ engine: { getRunByTicket: () => ok(runView({ rows })) } }));
    const items = document.querySelectorAll('#cr-body li.cr-row');
    expect([...items].map((li) => li.dataset.verdict)).toEqual(['ALLOW', 'REFUSE']);
  });

  test('shows an error when the FDK client fails to start', async () => {
    await boot(null, () => Promise.reject(new Error('no parent')));
    expect(bodyMessage()).toEqual({ type: 'error', text: expect.stringMatching(/could not start/i) });
  });

  test('shows an error when the ticket cannot be read', async () => {
    const client = fakeClient();
    client.data.get.mockImplementation(() => Promise.reject(new Error('denied')));
    await boot(client);
    expect(bodyMessage().type).toBe('error');
    expect(client.request.invokeTemplate).not.toHaveBeenCalled();
  });

  test('never builds an engine path from a ticket id that is not a positive integer', async () => {
    const client = fakeClient({ ticket: { id: '25/../../admin' } });
    await boot(client);
    expect(client.request.invokeTemplate).not.toHaveBeenCalled();
    expect(bodyMessage().type).toBe('error');
  });

  test('shows the HTTP status when the engine fails', async () => {
    await boot(fakeClient({ engine: { getRunByTicket: () => fail(500) } }));
    expect(bodyMessage()).toEqual({ type: 'error', text: expect.stringContaining('500') });
  });

  test('explains a rejected token by pointing at the app settings, never at the token itself', async () => {
    await boot(fakeClient({ engine: { getRunByTicket: () => fail(401) } }));
    expect(bodyMessage().text).toMatch(/settings/i);
  });
});
