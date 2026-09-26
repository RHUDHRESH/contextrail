/**
 * @vitest-environment jsdom
 */
// Verdict rows (CLAUDE.md §13.2): ALLOW with a verified tick, HOLD with approver and deadline, REFUSE struck
// through with the clause quoted verbatim. Refusals stay visible (P4); "verified" only ever comes from the engine's
// read-back flag, never from a state that merely looks successful (P3).

let V;

beforeEach(async () => {
  vi.resetModules();
  delete window.CRView;
  await import('../app/scripts/view.js');
  V = window.CRView;
});

function row(overrides) {
  return {
    action_id: 'a1', kind: 'grant', label: 'Jira: payments project', verdict: 'ALLOW', lamp: '✅',
    state: 'verified', rule_id: 'POL-ACC-001', clause: 'Role baseline access is granted.', approver_id: null,
    approver_name: null, explanation: null, explainer: null, verified: true, params_hash: 'h1',
    struck_through: false, connector_mode: 'FIXTURE', ...overrides
  };
}

const fmt = (iso) => 'fmt(' + iso + ')';

describe('rowModel', () => {
  test('ALLOW and read back: verified tick, no extra lines', () => {
    const m = V.rowModel(row(), fmt);
    expect(m).toMatchObject({ tone: 'allow', lamp: '✅', verified: true, struck: false, lines: [], rule: 'POL-ACC-001' });
    expect(m.stateText).toBe('Verified');
  });

  test('ALLOW that executed but was not read back is not verified', () => {
    const m = V.rowModel(row({ state: 'executed', verified: false }), fmt);
    expect(m.verified).toBe(false);
    expect(m.stateText).toBe('Executed, not verified yet');
  });

  test('a state of "verified" without the verified flag still earns no tick', () => {
    expect(V.rowModel(row({ state: 'verified', verified: false }), fmt).verified).toBe(false);
  });

  test('HOLD names the approver and the deadline', () => {
    const m = V.rowModel(row({
      verdict: 'HOLD', state: 'awaiting', verified: false, approver_id: 'security-oncall',
      approver_name: 'Meera Shah', deadline: '2026-09-26T11:30:00Z'
    }), fmt);
    expect(m).toMatchObject({ tone: 'hold', lamp: '🟠', struck: false, stateText: 'Awaiting approval' });
    expect(m.lines).toEqual(['Approver: Meera Shah', 'Deadline: fmt(2026-09-26T11:30:00Z)']);
  });

  test('HOLD without a display name falls back to the approver id, and says when no deadline is set', () => {
    const m = V.rowModel(row({ verdict: 'HOLD', state: 'awaiting', verified: false, approver_id: 'security-oncall' }), fmt);
    expect(m.lines).toEqual(['Approver: security-oncall', 'No deadline set']);
  });

  test('REFUSE is struck through and quotes the clause verbatim', () => {
    const clause = 'Contractors and vendors must not be issued production credentials.';
    const m = V.rowModel(row({ verdict: 'REFUSE', state: 'refused', verified: false, rule_id: 'POL-CTR-001', clause }), fmt);
    expect(m).toMatchObject({ tone: 'refuse', lamp: '⛔', struck: true, rule: 'POL-CTR-001', stateText: 'Refused' });
    expect(m.lines).toEqual(['“' + clause + '”']);
  });

  test('an unknown verdict is never shown as allowed', () => {
    const m = V.rowModel(row({ verdict: 'MAYBE' }), fmt);
    expect(m.tone).toBe('unknown');
    expect(m.lamp).not.toBe('✅');
    expect(m.verified).toBe(true);
  });
});

describe('renderRows', () => {
  const view = {
    counts: { allow: 1, hold: 1, refuse: 1, verified: 1, awaiting: 1, failed: 0 },
    rows: [
      row(),
      row({ action_id: 'a2', verdict: 'HOLD', state: 'awaiting', verified: false, approver_name: 'Meera Shah' }),
      row({ action_id: 'a3', verdict: 'REFUSE', state: 'refused', verified: false, clause: 'No prod admin.' })
    ]
  };

  test('renders one list item per row, in the engine\'s order, refusals included', () => {
    const items = V.renderRows(document, view, fmt).querySelectorAll('li.cr-row');
    expect([...items].map((li) => li.dataset.actionId)).toEqual(['a1', 'a2', 'a3']);
    expect([...items].map((li) => li.dataset.verdict)).toEqual(['ALLOW', 'HOLD', 'REFUSE']);
  });

  test('the refused label sits inside <s> and its clause is shown', () => {
    const refused = V.renderRows(document, view, fmt).querySelector('li.cr-row--refuse');
    expect(refused.querySelector('s.cr-row-label').textContent).toBe('Jira: payments project');
    expect(refused.querySelector('.cr-row-line').textContent).toBe('“No prod admin.”');
  });

  test('only the verified row carries the verified tick', () => {
    const ticks = V.renderRows(document, view, fmt).querySelectorAll('.cr-verified');
    expect(ticks).toHaveLength(1);
    expect(ticks[0].closest('li').dataset.actionId).toBe('a1');
  });

  test('prints the counts and each row\'s connector mode', () => {
    const out = V.renderRows(document, view, fmt);
    expect(out.querySelector('.cr-counts').textContent).toBe('1 allowed · 1 held · 1 refused · 1 verified');
    expect(out.querySelector('li .cr-row-mode').textContent).toBe('FIXTURE');
  });

  test('says so when the run has no actions yet', () => {
    const out = V.renderRows(document, { counts: {}, rows: [] }, fmt);
    expect(out.querySelector('.cr-rows-empty').textContent).toMatch(/no actions/i);
  });

  test('row text from the engine is inert text', () => {
    const out = V.renderRows(document, { counts: {}, rows: [row({ label: '<b>x</b>', clause: '<script>1</script>' })] }, fmt);
    expect(out.querySelector('b')).toBeNull();
    expect(out.querySelector('script')).toBeNull();
  });
});

describe('formatDeadline', () => {
  test('formats an ISO timestamp and leaves anything unparseable as written', () => {
    expect(V.formatDeadline('2026-09-26T11:30:00Z')).toMatch(/26|Sep|09/);
    expect(V.formatDeadline('end of day')).toBe('end of day');
  });
});
