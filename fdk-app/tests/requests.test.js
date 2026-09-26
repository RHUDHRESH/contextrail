// Request templates: the only way the app reaches the engine. The host comes from the non-secure engine_url
// iparam, the bearer token from the secure engine_token iparam, and nothing secret ever sits in a path or query.
const fs = require('fs');
const path = require('path');

const requests = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'requests.json'), 'utf8'));

describe('config/requests.json', () => {
  test('defines exactly getRunByTicket, startRun and getReceipt', () => {
    expect(Object.keys(requests).sort()).toEqual(['getReceipt', 'getRunByTicket', 'startRun']);
  });

  test.each(Object.keys(requests))('%s calls the engine host over HTTPS with the secure bearer token', (name) => {
    const { schema } = requests[name];
    expect(schema.protocol).toBe('https');
    expect(schema.host).toBe('<%= iparam.engine_url %>');
    expect(schema.path.startsWith('/')).toBe(true);
    expect(schema.headers.Authorization).toBe('Bearer <%= iparam.engine_token %>');
    expect(schema.headers['Content-Type']).toBe('application/json');
    expect(schema.query).toBeUndefined();
    expect(schema.path).not.toMatch(/token|iparam/);
  });

  test('getRunByTicket reads the run for the open ticket', () => {
    expect(requests.getRunByTicket.schema.method).toBe('GET');
    expect(requests.getRunByTicket.schema.path).toBe('/v1/runs/by-ticket/<%= context.ticket_id %>');
  });

  test('startRun posts a new run and is never retried by the platform (a write)', () => {
    expect(requests.startRun.schema.method).toBe('POST');
    expect(requests.startRun.schema.path).toBe('/v1/runs');
    expect(requests.startRun.options?.maxAttempts ?? 1).toBe(1);
  });

  test('getReceipt reads the receipt of one run', () => {
    expect(requests.getReceipt.schema.method).toBe('GET');
    expect(requests.getReceipt.schema.path).toBe('/v1/runs/<%= context.run_id %>/receipt');
  });

  test('reads may retry on network, 429 and 5xx errors within the platform limits', () => {
    for (const name of ['getRunByTicket', 'getReceipt']) {
      const { maxAttempts, retryDelay } = requests[name].options;
      expect(maxAttempts).toBeGreaterThanOrEqual(1);
      expect(maxAttempts).toBeLessThanOrEqual(5);
      expect(retryDelay % 100).toBe(0);
      expect(retryDelay).toBeLessThanOrEqual(1500);
    }
  });
});
