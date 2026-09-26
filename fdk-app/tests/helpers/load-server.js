// Loads server/server.js the way the FDK serverless runtime does: `exports = {...}` assigned in a sandbox that
// provides the platform globals ($request, renderData). Mirrors the official request-method-samples tests.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SERVER = path.join(__dirname, '..', '..', 'server', 'server.js');

function loadServer(globals) {
  const sandbox = { exports: {}, console: { log() {}, info() {}, error() {} }, ...globals };
  vm.runInNewContext(fs.readFileSync(SERVER, 'utf8'), sandbox, { filename: SERVER });
  return sandbox.exports;
}

module.exports = { loadServer };
