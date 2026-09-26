// onAppInstall: refuse an installation whose engine host or token is malformed, with a message the admin can act on.
const { loadServer } = require('./helpers/load-server');

const GOOD = { engine_url: 'contextrail.example.com', engine_token: 'fake-token-for-tests-0000' };

function install(iparams) {
  const renderData = vi.fn();
  const server = loadServer({ renderData, $request: { invokeTemplate: vi.fn() } });
  server.onAppInstallHandler({ iparams });
  return renderData;
}

describe('onAppInstallHandler', () => {
  test('allows the installation when the host and token are well formed', () => {
    const renderData = install(GOOD);
    expect(renderData).toHaveBeenCalledTimes(1);
    expect(renderData).toHaveBeenCalledWith();
  });

  test('blocks a host that carries a scheme, naming the expected format', () => {
    const renderData = install({ ...GOOD, engine_url: 'https://contextrail.example.com' });
    const [error] = renderData.mock.calls[0];
    expect(error.message).toMatch(/host/i);
    expect(error.message.length).toBeLessThanOrEqual(60);
  });

  test('blocks a missing or short token without echoing it', () => {
    const renderData = install({ ...GOOD, engine_token: 'abc' });
    const [error] = renderData.mock.calls[0];
    expect(error.message).toMatch(/token/i);
    expect(error.message).not.toContain('abc');
    expect(error.message.length).toBeLessThanOrEqual(60);
  });

  test.each([
    'http://contextrail.example.com',
    'contextrail.example.com/v1',
    'contextrail.example.com:8000',
    '10.0.0.12',
    'localhost'
  ])('blocks the same malformed host %j that the settings page rejects', (engineUrl) => {
    const [error] = install({ ...GOOD, engine_url: engineUrl }).mock.calls[0];
    expect(error.message).toMatch(/host/i);
  });

  test('does not block when the platform sends no iparams (the settings page already enforces required)', () => {
    expect(install({})).toHaveBeenCalledWith();
    expect(install(undefined)).toHaveBeenCalledWith();
  });
});
