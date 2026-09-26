/**
 * @vitest-environment jsdom
 */
// Polling: every 3 s while the run is running, never overlapping, and stopping as soon as it is not.
import { boot, fakeClient, ok, fail, runView, flush } from './helpers/sidebar.js';

function lookups(client) {
  return client.request.invokeTemplate.mock.calls.filter(([name]) => name === 'getRunByTicket').length;
}

function sequence(...answers) {
  let i = 0;
  return () => answers[Math.min(i++, answers.length - 1)]();
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('polling', () => {
  test('re-fetches the run every 3 seconds while it is running', async () => {
    const client = fakeClient({ engine: { getRunByTicket: () => ok(runView()) } });
    await boot(client);
    expect(lookups(client)).toBe(1);
    await vi.advanceTimersByTimeAsync(2999);
    expect(lookups(client)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(lookups(client)).toBe(2);
    await vi.advanceTimersByTimeAsync(3000);
    expect(lookups(client)).toBe(3);
  });

  test('stops on a final state and shows it', async () => {
    const client = fakeClient({
      engine: {
        getRunByTicket: sequence(() => ok(runView()), () => ok(runView({ status: 'done', stage: 'finalize' })))
      }
    });
    await boot(client);
    await vi.advanceTimersByTimeAsync(3000);
    expect(document.querySelector('#cr-status fw-pill').textContent).toBe('Done');
    await vi.advanceTimersByTimeAsync(60000);
    expect(lookups(client)).toBe(2);
  });

  test.each(['partial', 'failed', 'awaiting_approval', 'needs_input'])('does not poll a %s run', async (status) => {
    const client = fakeClient({ engine: { getRunByTicket: () => ok(runView({ status })) } });
    await boot(client);
    await vi.advanceTimersByTimeAsync(30000);
    expect(lookups(client)).toBe(1);
  });

  test('never starts a poll while the previous one is still in flight', async () => {
    let calls = 0;
    const client = fakeClient({
      engine: {
        getRunByTicket: () => {
          calls += 1;
          if (calls === 1) {
            return ok(runView());
          }
          return new Promise((resolve) => setTimeout(() => resolve({ status: 200, response: JSON.stringify(runView()) }), 10000));
        }
      }
    });
    await boot(client);
    await vi.advanceTimersByTimeAsync(3000);
    expect(calls).toBe(2);
    await vi.advanceTimersByTimeAsync(9999);
    expect(calls).toBe(2);
    await vi.advanceTimersByTimeAsync(1 + 3000);
    expect(calls).toBe(3);
  });

  test('an engine error stops the polling', async () => {
    const client = fakeClient({ engine: { getRunByTicket: sequence(() => ok(runView()), () => fail(500)) } });
    await boot(client);
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(30000);
    expect(lookups(client)).toBe(2);
  });

  test('a run started from the empty state is polled until it settles', async () => {
    const client = fakeClient({
      engine: {
        getRunByTicket: sequence(() => fail(404), () => ok(runView({ status: 'done' }))),
        startRun: () => ok(runView({ stage: 'discover' }))
      }
    });
    await boot(client);
    document.querySelector('fw-button#cr-run').dispatchEvent(new CustomEvent('fwClick'));
    await flush();
    await vi.advanceTimersByTimeAsync(3000);
    expect(document.querySelector('#cr-status fw-pill').textContent).toBe('Done');
    await vi.advanceTimersByTimeAsync(30000);
    expect(lookups(client)).toBe(2);
  });
});
