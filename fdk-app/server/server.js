exports = {
  // Refuses an installation whose engine host or token is malformed. The settings-page regex checks the same
  // shapes first; this is the server-side guard the platform runs before the install completes.
  onAppInstallHandler: function (args) {
    const iparams = args.iparams;
    if (!iparams || Object.keys(iparams).length === 0) {
      renderData();
      return;
    }
    const problem = installProblem(iparams);
    if (problem) {
      renderData({ message: problem });
      return;
    }
    renderData();
  }
};

const ENGINE_HOST = /^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
const ENGINE_TOKEN = /^\S{16,}$/;

function installProblem(iparams) {
  if (!ENGINE_HOST.test(String(iparams.engine_url || ''))) {
    return 'Engine host must be a host name, e.g. cr.example.com';
  }
  if (!ENGINE_TOKEN.test(String(iparams.engine_token || ''))) {
    return 'Engine token must be 16+ characters, no spaces';
  }
  return null;
}
