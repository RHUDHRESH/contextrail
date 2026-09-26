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

  window.CRView = {
    el: el,
    statusModel: statusModel,
    modeModel: modeModel,
    renderHeader: renderHeader
  };
})();
