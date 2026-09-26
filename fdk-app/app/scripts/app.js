(function () {
  document.addEventListener('DOMContentLoaded', start);

  function start() {
    app.initialized().then(showReady).catch(showInitError);
  }

  function showReady() {
    setBody('info', 'Connected to Freshservice.');
  }

  function showInitError() {
    setBody('error', 'ContextRail could not start in this ticket. Reload the page to try again.');
  }

  function setBody(type, text) {
    const body = document.getElementById('cr-body');
    const message = document.createElement('fw-inline-message');
    message.setAttribute('type', type);
    message.setAttribute('closable', 'false');
    message.textContent = text;
    body.replaceChildren(message);
  }
})();
