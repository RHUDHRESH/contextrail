// Contract tests for the app manifest: the shape fdk validate and the Freshservice runtime rely on.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), 'utf8'));
const manifest = readJson('manifest.json');

describe('manifest.json', () => {
  test('targets Platform 3.0 with the service_ticket ticket_sidebar location', () => {
    expect(manifest['platform-version']).toBe('3.0');
    expect(manifest.product).toBeUndefined();
    const sidebar = manifest.modules.service_ticket.location.ticket_sidebar;
    expect(sidebar).toEqual({ url: 'index.html', icon: 'styles/images/icon.svg' });
  });

  test('every location page and icon declared in the manifest exists under app/', () => {
    const sidebar = manifest.modules.service_ticket.location.ticket_sidebar;
    for (const rel of [sidebar.url, sidebar.icon]) {
      expect(fs.existsSync(path.join(ROOT, 'app', rel)), `missing app/${rel}`).toBe(true);
    }
  });

  test('pins the Node 24.x and FDK 10.x engines the toolkit requires', () => {
    expect(manifest.engines.node).toMatch(/^24\.\d+\.\d+$/);
    expect(manifest.engines.fdk).toMatch(/^10\.\d+\.\d+$/);
  });

  test('registers every request template in modules.common.requests, and nothing else', () => {
    const templates = Object.keys(readJson('config/requests.json')).sort();
    expect(Object.keys(manifest.modules.common.requests).sort()).toEqual(templates);
    for (const name of templates) {
      expect(manifest.modules.common.requests[name]).toEqual({});
    }
  });

  test('declares the vitest unit-test script that fdk validate requires', () => {
    expect(manifest.scripts['fdk-unit-test']).toBe('vitest run --coverage');
  });

  test('validates the non-empty iparams at install time through onAppInstall', () => {
    expect(manifest.modules.common.events.onAppInstall).toEqual({ handler: 'onAppInstallHandler' });
  });

  test('every event handler named in the manifest is exported by server/server.js', () => {
    const { loadServer } = require('./helpers/load-server');
    const server = loadServer({ renderData() {}, $request: {} });
    const events = Object.values(manifest.modules).flatMap((m) => Object.values(m.events || {}));
    expect(events.length).toBeGreaterThan(0);
    for (const { handler } of events) {
      expect(typeof server[handler], handler).toBe('function');
    }
  });

  test('the app icon is declared 64x64, the marketplace baseline', () => {
    const svg = fs.readFileSync(path.join(ROOT, 'app', 'styles', 'images', 'icon.svg'), 'utf8');
    expect(svg).toMatch(/width="64"/);
    expect(svg).toMatch(/height="64"/);
  });
});
