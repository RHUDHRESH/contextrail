/**
 * @vitest-environment jsdom
 */
// No run yet (engine 404): the empty state starts one through the startRun request template, exactly once.
import { boot, fakeClient, ok, fail, runView, bodyMessage, flush } from './helpers/sidebar.js';

function runButton() {
  return document.querySelector('#cr-body fw-button#cr-run');
}

async function click(button) {
  button.dispatchEvent(new CustomEvent('fwClick'));
  await flush();
}

describe('empty state', () => {
  test('a ticket with no run shows the start button, not an error', async () => {
    await boot(fakeClient({ engine: { getRunByTicket: () => fail(404) } }));
    expect(runButton().textContent).toBe('Run ContextRail on this ticket');
    expect(bodyMessage()).toBeNull();
  });

  test('the button posts startRun with the ticket id and idempotency key, then shows the new run', async () => {
    const client = fakeClient({
      engine: { getRunByTicket: () => fail(404), startRun: () => ok(runView({ stage: 'discover' })) }
    });
    await boot(client);
    await click(runButton());
    expect(client.request.invokeTemplate).toHaveBeenCalledWith('startRun', {
      body: JSON.stringify({
        ticket_id: 25, source: 'freshservice', trigger: 'fdk_sidebar', idempotency_key: 'freshservice:ticket:25'
      })
    });
    expect(document.querySelector('#cr-status fw-pill').textContent).toBe('Running · Discover');
  });

  test('a double click starts one run, not two', async () => {
    let finish;
    const client = fakeClient({
      engine: {
        getRunByTicket: () => fail(404),
        startRun: () => new Promise((resolve) => { finish = resolve; })
      }
    });
    await boot(client);
    const button = runButton();
    button.dispatchEvent(new CustomEvent('fwClick'));
    button.dispatchEvent(new CustomEvent('fwClick'));
    await flush();
    expect(button.hasAttribute('loading')).toBe(true);
    finish({ status: 202, response: JSON.stringify(runView()) });
    await flush();
    const starts = client.request.invokeTemplate.mock.calls.filter(([name]) => name === 'startRun');
    expect(starts).toHaveLength(1);
  });

  test('a failed start keeps the button and shows the error above it', async () => {
    await boot(fakeClient({ engine: { getRunByTicket: () => fail(404), startRun: () => fail(500) } }));
    await click(runButton());
    expect(bodyMessage()).toEqual({ type: 'error', text: expect.stringContaining('500') });
    expect(runButton()).not.toBeNull();
  });

  test('if another trigger already started the run (409), the sidebar loads that run instead', async () => {
    let lookups = 0;
    const client = fakeClient({
      engine: {
        getRunByTicket: () => (lookups++ === 0 ? fail(404) : ok(runView({ stage: 'plan' }))),
        startRun: () => fail(409)
      }
    });
    await boot(client);
    await click(runButton());
    expect(document.querySelector('#cr-status fw-pill').textContent).toBe('Running · Plan');
  });
});
