// Pure rendering of the engine's RunView (engine/contextrail/surfaces/presenter.py). Nothing here decides a
// verdict: it only turns what the engine said into Crayons elements, always through textContent/attributes.
(function () {
  const STATUS = new Map([
    ['running', { label: 'Running', color: 'blue' }],
    ['needs_input', { label: 'Needs input', color: 'yellow' }],
    ['awaiting_approval', { label: 'Awaiting approval', color: 'yellow' }],
    ['partial', { label: 'Partial', color: 'grey' }],
    ['done', { label: 'Done', color: 'green' }],
    ['failed', { label: 'Failed', color: 'red' }]
  ]);
  const MODE_COLOR = new Map([['LIVE', 'green'], ['FIXTURE', 'yellow'], ['UNVERIFIED', 'grey']]);
  const VERDICT = new Map([
    ['ALLOW', { tone: 'allow', lamp: '✅' }],
    ['HOLD', { tone: 'hold', lamp: '🟠' }],
    ['REFUSE', { tone: 'refuse', lamp: '⛔' }]
  ]);
  const UNKNOWN_VERDICT = { tone: 'unknown', lamp: '❔' };
  const STATE_TEXT = new Map([
    ['planned', 'Planned'],
    ['awaiting', 'Awaiting approval'],
    ['approved', 'Approved, not executed yet'],
    ['refused', 'Refused'],
    ['executed', 'Executed, not verified yet'],
    ['verified', 'Not verified'],
    ['failed', 'Failed'],
    ['unknown', 'Outcome unknown: reconciling before any retry']
  ]);

  function el(doc, tag, attrs, text) {
    const node = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      node.setAttribute(name, attrs[name]);
    });
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function statusModel(status, stage) {
    const known = STATUS.get(status);
    if (!known) {
      return { label: String(status), color: 'grey' };
    }
    const label = status === 'running' && stage ? known.label + ' · ' + capitalize(String(stage)) : known.label;
    return { label: label, color: known.color };
  }

  // LIVE only when every connector the run touched is LIVE (D-004): one fixture makes the run FIXTURE.
  function modeLabel(values) {
    if (values.length > 0 && values.every(function (v) { return v === 'LIVE'; })) {
      return 'LIVE';
    }
    return values.indexOf('FIXTURE') >= 0 ? 'FIXTURE' : 'UNVERIFIED';
  }

  function modeModel(modes, replay) {
    const names = Object.keys(modes || {}).sort();
    const label = modeLabel(names.map(function (n) { return modes[n]; }));
    return {
      label: label,
      color: MODE_COLOR.get(label),
      detail: names.map(function (n) { return n + ' ' + modes[n]; }).join(' · '),
      replay: Boolean(replay)
    };
  }

  function renderHeader(doc, view) {
    const status = statusModel(view.status, view.stage);
    const mode = modeModel(view.modes, view.replay);
    const badges = el(doc, 'div', { class: 'cr-badges' });
    badges.append(el(doc, 'fw-pill', { class: 'cr-status-pill', color: status.color }, status.label));
    badges.append(el(doc, 'fw-label', { class: 'cr-mode', value: mode.label, color: mode.color }));
    if (mode.replay) {
      badges.append(el(doc, 'fw-label', { class: 'cr-replay', value: 'REPLAY', color: 'blue' }));
    }
    const box = el(doc, 'div', { class: 'cr-status' });
    box.append(badges, el(doc, 'p', { class: 'cr-mode-detail' }, mode.detail));
    return box;
  }

  function formatDeadline(iso) {
    const at = new Date(iso);
    if (Number.isNaN(at.getTime())) {
      return String(iso);
    }
    return at.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function holdLines(row, fmt) {
    const approver = row.approver_name || row.approver_id || 'no approver named';
    return ['Approver: ' + approver, row.deadline ? 'Deadline: ' + fmt(row.deadline) : 'No deadline set'];
  }

  function refuseLines(row) {
    return [row.clause ? '“' + row.clause + '”' : 'No clause recorded'];
  }

  function linesFor(tone, row, fmt) {
    if (tone === 'hold') {
      return holdLines(row, fmt);
    }
    return tone === 'refuse' ? refuseLines(row) : [];
  }

  // Verified is the engine's read-back flag and nothing else (P3): an executed row is not a verified row.
  function stateTextOf(row) {
    if (row.verified === true) {
      return 'Verified';
    }
    return STATE_TEXT.get(row.state) || String(row.state);
  }

  function rowModel(row, fmt) {
    const verdict = VERDICT.get(row.verdict) || UNKNOWN_VERDICT;
    return {
      id: String(row.action_id),
      verdict: String(row.verdict),
      tone: verdict.tone,
      lamp: verdict.lamp,
      label: String(row.label),
      struck: verdict.tone === 'refuse' || row.struck_through === true,
      verified: row.verified === true,
      stateText: stateTextOf(row),
      rule: row.rule_id || '',
      lines: linesFor(verdict.tone, row, fmt || formatDeadline),
      mode: row.connector_mode || 'unknown'
    };
  }

  function renderRow(doc, model) {
    const item = el(doc, 'li', { class: 'cr-row cr-row--' + model.tone, 'data-verdict': model.verdict });
    item.dataset.actionId = model.id;
    const main = el(doc, 'div', { class: 'cr-row-main' });
    main.append(el(doc, model.struck ? 's' : 'span', { class: 'cr-row-label' }, model.label));
    model.lines.forEach(function (line) {
      main.append(el(doc, 'span', { class: 'cr-row-line' }, line));
    });
    const meta = el(doc, 'span', { class: 'cr-row-meta' });
    meta.append(el(doc, 'span', { class: model.verified ? 'cr-verified' : 'cr-state' }, (model.verified ? '✓ ' : '') + model.stateText));
    meta.append(el(doc, 'span', { class: 'cr-row-rule' }, model.rule));
    meta.append(el(doc, 'span', { class: 'cr-row-mode' }, model.mode));
    main.append(meta);
    item.append(el(doc, 'span', { class: 'cr-lamp', 'aria-hidden': 'true' }, model.lamp), main);
    return item;
  }

  function countsText(counts) {
    const c = counts || {};
    return [
      (c.allow || 0) + ' allowed', (c.hold || 0) + ' held', (c.refuse || 0) + ' refused', (c.verified || 0) + ' verified'
    ].join(' · ');
  }

  function renderRows(doc, view, fmt) {
    const box = el(doc, 'div', { class: 'cr-rows-box' });
    const rows = view.rows || [];
    if (rows.length === 0) {
      box.append(el(doc, 'p', { class: 'cr-rows-empty' }, 'No actions planned yet.'));
      return box;
    }
    const list = el(doc, 'ul', { class: 'cr-rows', 'aria-label': 'Actions and verdicts' });
    rows.forEach(function (r) {
      list.append(renderRow(doc, rowModel(r, fmt)));
    });
    box.append(el(doc, 'p', { class: 'cr-counts' }, countsText(view.counts)), list);
    return box;
  }

  function renderEmpty(doc, errorText) {
    const box = el(doc, 'div', { class: 'cr-empty' });
    if (errorText) {
      box.append(el(doc, 'fw-inline-message', { type: 'error', closable: 'false' }, errorText));
    }
    box.append(el(doc, 'p', { class: 'cr-empty-text' },
      'ContextRail has not run on this ticket yet. Running it checks every requested action against written policy.'));
    box.append(el(doc, 'fw-button', { id: 'cr-run', color: 'primary' }, 'Run ContextRail on this ticket'));
    return box;
  }

  // The same key whichever trigger starts the run (sidebar, onTicketCreate, Workflow Automator webhook), so the
  // engine can dedupe them into one run for the ticket (CLAUDE.md §0 rule 5).
  function startRunBody(ticketId, trigger) {
    return {
      ticket_id: ticketId,
      source: 'freshservice',
      trigger: trigger,
      idempotency_key: 'freshservice:ticket:' + ticketId
    };
  }

  window.CRView = {
    el: el,
    renderEmpty: renderEmpty,
    startRunBody: startRunBody,
    statusModel: statusModel,
    modeModel: modeModel,
    renderHeader: renderHeader,
    formatDeadline: formatDeadline,
    rowModel: rowModel,
    renderRows: renderRows
  };
})();
