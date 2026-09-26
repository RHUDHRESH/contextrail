// Boots the real sidebar (app/index.html body + app/scripts/*.js) in jsdom against a fake FDK client.
import fs from 'fs';
import path from 'path';

const INDEX = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'index.html'), 'utf8');

export const RUN_ID = '3f2b6c1e-8d4a-4b7e-9c1a-2e5f7a9b0c3d';

export function runView(overrides) {
  return {
    run_id: RUN_ID,
    status: 'running',
    stage: 'govern',
    source: 'freshservice',
    request_text: 'Give Anil the same access as Rahul',
    subject: 'Anil Kumar',
    peer: 'Rahul Mehta',
    rows: [],
    counts: { allow: 0, hold: 0, refuse: 0, verified: 0, awaiting: 0, failed: 0 },
    capsule_digest: '9f3a0c',
    modes: { entitlements: 'FIXTURE', github: 'FIXTURE' },
    replay: false,
    needs: [],
    ...overrides
  };
}

export function ok(body) {
  return Promise.resolve({ status: 200, headers: {}, response: JSON.stringify(body) });
}

export function fail(status) {
  return Promise.reject({ status: status, response: '{"detail":"x"}', errorSource: 'APP' });
}

// `engine` maps a template name to a function (options) => Promise, so a test can answer each call.
export function fakeClient({ ticket = { id: 25 }, engine = {} } = {}) {
  return {
    data: { get: vi.fn(() => Promise.resolve({ ticket: ticket })) },
    request: {
      invokeTemplate: vi.fn((name, options) => {
        const answer = engine[name];
        return answer ? answer(options) : Promise.reject({ status: 500, response: 'no fake for ' + name });
      })
    },
    interface: { trigger: vi.fn(() => Promise.resolve({ message: 'ok' })) }
  };
}

export async function flush() {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
  }
}

export async function boot(client, initialized) {
  document.body.innerHTML = INDEX.match(/<body>([\s\S]*)<\/body>/)[1];
  window.app = { initialized: initialized || (() => Promise.resolve(client)) };
  vi.resetModules();
  delete window.CRView;
  await import('../../app/scripts/view.js');
  await import('../../app/scripts/app.js');
  await flush();
}

export function bodyMessage() {
  const msg = document.querySelector('#cr-body fw-inline-message');
  return msg ? { type: msg.getAttribute('type'), text: msg.textContent } : null;
}
