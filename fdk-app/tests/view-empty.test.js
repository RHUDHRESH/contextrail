/**
 * @vitest-environment jsdom
 */
// Empty state: the ticket has no ContextRail run yet, so offer to start one.

let V;

beforeEach(async () => {
  vi.resetModules();
  delete window.CRView;
  await import('../app/scripts/view.js');
  V = window.CRView;
});

describe('renderEmpty', () => {
  test('explains there is no run and offers the start button', () => {
    const box = V.renderEmpty(document);
    expect(box.querySelector('.cr-empty-text').textContent).toMatch(/has not run on this ticket/i);
    const button = box.querySelector('fw-button#cr-run');
    expect(button.textContent).toBe('Run ContextRail on this ticket');
    expect(button.getAttribute('color')).toBe('primary');
    expect(box.querySelector('fw-inline-message')).toBeNull();
  });

  test('can carry an error above the button so the agent can retry', () => {
    const box = V.renderEmpty(document, 'The engine returned an error (HTTP 500).');
    const message = box.querySelector('fw-inline-message');
    expect(message.getAttribute('type')).toBe('error');
    expect(message.textContent).toBe('The engine returned an error (HTTP 500).');
    expect(box.querySelector('fw-button#cr-run')).not.toBeNull();
  });
});

describe('startRunBody', () => {
  test('names the ticket, the channel and an idempotency key derived from the ticket id', () => {
    expect(V.startRunBody(25, 'fdk_sidebar')).toEqual({
      ticket_id: 25,
      source: 'freshservice',
      trigger: 'fdk_sidebar',
      idempotency_key: 'freshservice:ticket:25'
    });
  });
});
