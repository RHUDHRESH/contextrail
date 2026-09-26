// Installation parameters: the engine host and the engine token. The token is secure, so Freshworks stores it
// encrypted and only request-template headers can read it; the app's own code never sees it.
const fs = require('fs');
const path = require('path');

const iparams = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'iparams.json'), 'utf8'));

function regexOf(field, name) {
  return new RegExp(iparams[field].regex[name]);
}

describe('config/iparams.json', () => {
  test('declares exactly the engine host and the engine token, both required', () => {
    expect(Object.keys(iparams).sort()).toEqual(['engine_token', 'engine_url']);
    expect(iparams.engine_url.required).toBe(true);
    expect(iparams.engine_token.required).toBe(true);
  });

  test('the engine token is secure and the engine host is not (hosts cannot use secure iparams)', () => {
    expect(iparams.engine_token.secure).toBe(true);
    expect(iparams.engine_url.secure).not.toBe(true);
  });

  test('every regex has a specific error message next to it', () => {
    for (const field of Object.keys(iparams)) {
      const names = Object.keys(iparams[field].regex).filter((k) => !k.endsWith('-error'));
      expect(names.length).toBeGreaterThan(0);
      for (const name of names) {
        expect(iparams[field].regex[`${name}-error`]).toMatch(/\w{3,}.*e\.g\.|characters/);
      }
    }
  });

  test('the engine host accepts a bare host name', () => {
    const host = regexOf('engine_url', 'engine-host');
    expect(host.test('contextrail.example.com')).toBe(true);
    expect(host.test('cr-engine.ap-south-1.example.co')).toBe(true);
  });

  test.each([
    'https://contextrail.example.com',
    'http://contextrail.example.com',
    'contextrail.example.com/v1',
    'contextrail.example.com:8000',
    '10.0.0.12',
    'localhost',
    ' contextrail.example.com'
  ])('the engine host rejects %j (scheme, path, port, IP or bare name)', (value) => {
    expect(regexOf('engine_url', 'engine-host').test(value)).toBe(false);
  });

  test('the engine token must be at least 16 non-space characters', () => {
    const token = regexOf('engine_token', 'engine-token');
    expect(token.test('x'.repeat(16))).toBe(true);
    expect(token.test('short-token')).toBe(false);
    expect(token.test('has a space in the middle of it')).toBe(false);
  });
});
