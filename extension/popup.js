const $ = (selector) => document.querySelector(selector);

function request(op) {
  return chrome.runtime.sendMessage({op}).then((response) => {
    if (response?.error) throw new Error(response.error);
    return response;
  });
}

function label(element, text, kind = '') {
  element.textContent = text;
  element.className = kind;
}

function render(state) {
  $('#version').textContent = `v${state.version}`;
  label($('#daemon'), state.daemonConnected ? 'Online' : 'Offline', state.daemonConnected ? 'good' : 'bad');
  label($('#backend'), state.backendConnected ? 'Active' : 'Idle', state.backendConnected ? 'good' : '');
  label($('#tab'), state.weavyTabCount ? `${state.weavyTabCount} open` : 'Not found', state.weavyTabCount ? 'good' : 'bad');
  label($('#debugger'), state.attachedTabId ? 'Attached' : 'Standby', state.attachedTabId ? 'good' : '');
  $('#last-command').textContent = state.lastCommand || '—';
  $('#last-activity').textContent = state.lastActivity ? new Date(state.lastActivity).toLocaleTimeString() : '—';
  $('#flow-id').textContent = state.currentFlowId || '—';

  const hero = $('#hero');
  if (state.lastError) {
    hero.className = 'hero error';
    $('#headline').textContent = 'Needs attention';
    $('#summary').textContent = state.lastError;
  } else if (state.daemonConnected && state.weavyTabCount) {
    hero.className = 'hero ready';
    $('#headline').textContent = 'Backend ready';
    $('#summary').textContent = 'Python service can control Weavy';
  } else if (state.weavyTabCount) {
    hero.className = 'hero waiting';
    $('#headline').textContent = 'Start Python backend';
    $('#summary').textContent = 'Run python3 -m weavy.bridge_server';
  } else {
    hero.className = 'hero error';
    $('#headline').textContent = 'Open Weavy first';
    $('#summary').textContent = 'No app.weavy.ai tab detected';
  }

  const card = $('#tab-card');
  if (state.tabUrl) {
    card.classList.remove('hidden');
    $('#tab-title').textContent = state.tabTitle || 'Weavy';
    $('#tab-url').textContent = state.tabUrl;
  } else card.classList.add('hidden');
}

async function refresh() {
  try { render(await request('ui.status')); }
  catch (error) { $('#message').textContent = error.message; $('#message').className = 'message error'; }
}

$('#test').addEventListener('click', async () => {
  const button = $('#test');
  button.disabled = true;
  $('#message').textContent = 'Testing browser access…';
  $('#message').className = 'message';
  try {
    const result = await request('ui.test');
    $('#message').textContent = result.page?.canvas ? 'Working: Weavy canvas access verified.' : 'Connected: dashboard access verified.';
    $('#message').className = 'message success';
  } catch (error) {
    $('#message').textContent = error.message;
    $('#message').className = 'message error';
  } finally { button.disabled = false; await refresh(); }
});

$('#open').addEventListener('click', async () => {
  try { await request('ui.openWeavy'); window.close(); }
  catch (error) { $('#message').textContent = error.message; $('#message').className = 'message error'; }
});

refresh();
setInterval(refresh, 1500);
