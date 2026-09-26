/**
 * @vitest-environment jsdom
 */
// The sidebar header: the run's status pill and the honest connector-mode badge (CLAUDE.md §0 rule 4, D-004).

let V;

beforeEach(async () => {
  vi.resetModules();
  delete window.CRView;
  await import('../app/scripts/view.js');
  V = window.CRView;
});

describe('statusModel', () => {
  test.each([
    ['running', 'govern', 'Running · Govern', 'blue'],
    ['running', null, 'Running', 'blue'],
    ['needs_input', 'discover', 'Needs input', 'yellow'],
    ['awaiting_approval', 'approve', 'Awaiting approval', 'yellow'],
    ['partial', 'finalize', 'Partial', 'grey'],
    ['done', 'finalize', 'Done', 'green'],
    ['failed', 'execute', 'Failed', 'red']
  ])('%s at stage %s -> %s (%s)', (status, stage, label, color) => {
    expect(V.statusModel(status, stage)).toEqual({ label, color });
  });

  test('an unknown status is shown as-is, never dressed up as a known one', () => {
    expect(V.statusModel('paused', null)).toEqual({ label: 'paused', color: 'grey' });
  });
});

describe('modeModel', () => {
  test('LIVE only when every connector in the run is LIVE', () => {
    const m = V.modeModel({ freshservice: 'LIVE', github: 'LIVE' }, false);
    expect(m).toEqual({ label: 'LIVE', color: 'green', detail: 'freshservice LIVE · github LIVE', replay: false });
  });

  test('any FIXTURE connector makes the badge FIXTURE, and the detail names each one', () => {
    const m = V.modeModel({ github: 'FIXTURE', entitlements: 'FIXTURE', freshservice: 'LIVE' }, false);
    expect(m.label).toBe('FIXTURE');
    expect(m.color).toBe('yellow');
    expect(m.detail).toBe('entitlements FIXTURE · freshservice LIVE · github FIXTURE');
  });

  test('no modes or unknown modes are UNVERIFIED, never LIVE', () => {
    expect(V.modeModel({}, false).label).toBe('UNVERIFIED');
    expect(V.modeModel(undefined, false).label).toBe('UNVERIFIED');
    expect(V.modeModel({ github: 'unknown' }, false).label).toBe('UNVERIFIED');
  });

  test('carries the replay flag through', () => {
    expect(V.modeModel({ github: 'LIVE' }, true).replay).toBe(true);
  });
});

describe('renderHeader', () => {
  const view = { status: 'running', stage: 'compile', modes: { github: 'FIXTURE' }, replay: false };

  test('renders a Crayons pill for the status and a label for the mode', () => {
    const el = V.renderHeader(document, view);
    const pill = el.querySelector('fw-pill');
    expect(pill.getAttribute('color')).toBe('blue');
    expect(pill.textContent).toBe('Running · Compile');
    const mode = el.querySelector('fw-label.cr-mode');
    expect(mode.getAttribute('value')).toBe('FIXTURE');
    expect(mode.getAttribute('color')).toBe('yellow');
    expect(el.querySelector('.cr-mode-detail').textContent).toBe('github FIXTURE');
    expect(el.querySelector('.cr-replay')).toBeNull();
  });

  test('shows a REPLAY label when the answer came from the replay tier', () => {
    const el = V.renderHeader(document, { ...view, replay: true });
    expect(el.querySelector('fw-label.cr-replay').getAttribute('value')).toBe('REPLAY');
  });

  test('engine text is rendered as text, never as markup', () => {
    const el = V.renderHeader(document, { ...view, status: '<img src=x onerror=alert(1)>' });
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('fw-pill').textContent).toBe('<img src=x onerror=alert(1)>');
  });
});
