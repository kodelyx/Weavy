const BRIDGE_URL = 'ws://127.0.0.1:8765';
const WEAVY_URLS = ['https://app.weavy.ai/', 'https://api.weavy.ai/'];
const ALLOWED_COOKIE_DOMAINS = new Set(['weavy.ai', '.weavy.ai', 'app.weavy.ai', 'api.weavy.ai']);
const BLOCKED_CDP_COOKIE_METHODS = new Set([
  'Network.clearBrowserCookies',
  'Network.deleteCookies',
  'Network.getAllCookies',
  'Network.getCookies',
  'Network.setCookie',
  'Network.setCookies',
  'Storage.clearCookies',
  'Storage.getCookies',
  'Storage.setCookies',
]);

let socket = null;
let reconnectTimer = null;
let attachedTabId = null;
const eventQueue = [];
let currentFlowId = null;
const bridgeState = {
  daemonConnected: false,
  backendConnected: false,
  attachedTabId: null,
  tabTitle: null,
  tabUrl: null,
  lastCommand: null,
  lastError: null,
  lastActivity: null,
  currentFlowId: null,
};

function updateState(values) {
  Object.assign(bridgeState, values, {lastActivity: Date.now()});
}

function send(payload) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function flowIdFromUrl(url) {
  const match = String(url || '').match(/^https:\/\/app\.weavy\.ai\/flow\/([^/?#]+)/);
  return match ? normalizeFlowId(match[1]) : null;
}

function normalizeFlowId(value) {
  const flowId = String(value || '').trim();
  if (!/^[A-Za-z0-9_-]{8,128}$/.test(flowId)) return null;
  return flowId;
}

async function waitForTab(tabId, predicate, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    if (predicate(tab)) return tab;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Weavy tab did not become ready');
}

async function findWeavyTab() {
  const tabs = await chrome.tabs.query({url: ['https://app.weavy.ai/*']});
  const existing = tabs.find((item) => item.active) || tabs[0];
  if (existing?.id) return existing;

  const created = await chrome.tabs.create({url: 'https://app.weavy.ai/', active: true});
  if (!created?.id) throw new Error('Could not open Weavy');
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(created.id);
    if (tab.status === 'complete' && tab.url?.startsWith('https://app.weavy.ai/')) return tab;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Weavy opened but did not finish loading');
}

async function openUrl(url, active = false) {
  const created = await chrome.tabs.create({url, active});
  if (!created?.id) throw new Error('Could not open Weavy');
  return waitForTab(created.id, (tab) => tab.status === 'complete' && tab.url?.startsWith('https://app.weavy.ai/'));
}

async function attach(tabId) {
  if (attachedTabId === tabId) return;
  if (attachedTabId !== null) {
    await chrome.debugger.detach({tabId: attachedTabId}).catch(() => {});
  }
  await chrome.debugger.attach({tabId}, '1.3');
  attachedTabId = tabId;
  await chrome.debugger.sendCommand({tabId}, 'Runtime.enable');
  await chrome.debugger.sendCommand({tabId}, 'Page.enable');
  await chrome.debugger.sendCommand({tabId}, 'DOM.enable');
  await chrome.debugger.sendCommand({tabId}, 'Network.enable');
  const tab = await chrome.tabs.get(tabId);
  const flowId = flowIdFromUrl(tab.url);
  if (flowId) currentFlowId = flowId;
  updateState({attachedTabId: tabId, tabTitle: tab.title || null, tabUrl: tab.url || null, currentFlowId, lastError: null});
}

async function ensureAttached(tabId = null) {
  let resolved = null;
  if (tabId) resolved = await chrome.tabs.get(tabId);
  else if (attachedTabId !== null) resolved = await chrome.tabs.get(attachedTabId).catch(() => null);
  if (!resolved) resolved = await findWeavyTab();
  if (!resolved.url?.startsWith('https://app.weavy.ai/')) throw new Error('Bridge only attaches to app.weavy.ai');
  await attach(resolved.id);
  return resolved;
}

async function createFlowFromDashboard() {
  const dashboards = await chrome.tabs.query({url: ['https://app.weavy.ai/']});
  const tab = dashboards[0] || await openUrl('https://app.weavy.ai/');
  await attach(tab.id);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const evaluated = await chrome.debugger.sendCommand({tabId: tab.id}, 'Runtime.evaluate', {
      expression: `(() => {
        const button = Array.from(document.querySelectorAll('button')).find(element =>
          element.offsetParent !== null && element.innerText.trim() === 'Create New File');
        if (!button) return false;
        button.click();
        return true;
      })()`,
      returnByValue: true,
    });
    if (evaluated?.result?.value) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const flowTab = await waitForTab(tab.id, (item) => Boolean(flowIdFromUrl(item.url)), 20000);
  await attach(flowTab.id);
  currentFlowId = flowIdFromUrl(flowTab.url);
  updateState({currentFlowId, tabUrl: flowTab.url, tabTitle: flowTab.title || null});
  return flowTab;
}

async function waitForFlowCanvas(tabId, expectedFlowId, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    const flowId = flowIdFromUrl(tab.url);
    if (flowId && flowId !== expectedFlowId) throw new Error(`Opened wrong Weavy flow: ${flowId}`);
    const evaluated = await chrome.debugger.sendCommand({tabId}, 'Runtime.evaluate', {
      expression: 'Boolean(document.querySelector(".react-flow"))', returnByValue: true,
    }).catch(() => null);
    if (flowId === expectedFlowId && evaluated?.result?.value === true) return tab;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Weavy flow canvas did not load: ${expectedFlowId}`);
}

async function ensureFlow(flowId = null, autoCreate = true) {
  const tabs = await chrome.tabs.query({url: ['https://app.weavy.ai/*']});
  const flowTabs = tabs.filter((tab) => flowIdFromUrl(tab.url));
  let tab = null;

  if (flowId) {
    flowId = normalizeFlowId(flowId);
    if (!flowId) throw new Error('Invalid Weavy flow ID');
    tab = flowTabs.find((item) => flowIdFromUrl(item.url) === flowId) || null;
    if (!tab) tab = await openUrl(`https://app.weavy.ai/flow/${encodeURIComponent(flowId)}`);
    if (flowIdFromUrl(tab.url) !== flowId) throw new Error(`Weavy flow not available: ${flowId}`);
  } else if (currentFlowId) {
    tab = flowTabs.find((item) => flowIdFromUrl(item.url) === currentFlowId) || null;
    if (!tab) {
      try { tab = await openUrl(`https://app.weavy.ai/flow/${encodeURIComponent(currentFlowId)}`); }
      catch { currentFlowId = null; }
    }
  }

  if (!tab && attachedTabId !== null) {
    const attached = await chrome.tabs.get(attachedTabId).catch(() => null);
    if (flowIdFromUrl(attached?.url)) tab = attached;
  }
  if (!tab) tab = flowTabs.find((item) => item.active) || flowTabs[0] || null;
  if (!tab && autoCreate) tab = await createFlowFromDashboard();
  if (!tab) return null;

  await attach(tab.id);
  currentFlowId = flowIdFromUrl(tab.url);
  await waitForFlowCanvas(tab.id, currentFlowId);
  updateState({currentFlowId, tabUrl: tab.url, tabTitle: tab.title || null});
  return {
    tabId: tab.id,
    title: tab.title,
    flowId: currentFlowId,
    flowUrl: tab.url,
  };
}

function cookieAllowed(cookie) {
  return cookie?.domain && ALLOWED_COOKIE_DOMAINS.has(cookie.domain);
}

async function cookieList(details = {}) {
  const results = [];
  for (const url of WEAVY_URLS) {
    results.push(...await chrome.cookies.getAll({...details, url}));
  }
  const unique = new Map();
  for (const cookie of results) {
    if (cookieAllowed(cookie)) unique.set(`${cookie.storeId}:${cookie.domain}:${cookie.path}:${cookie.name}`, cookie);
  }
  return [...unique.values()];
}

async function cookieSet(details) {
  const url = new URL(details.url || 'https://app.weavy.ai/');
  if (!['app.weavy.ai', 'api.weavy.ai'].includes(url.hostname)) throw new Error('Cookie URL must be Weavy');
  if (details.domain && !ALLOWED_COOKIE_DOMAINS.has(details.domain)) throw new Error('Cookie domain must be Weavy');
  return chrome.cookies.set(details);
}

async function cookieRemove(details) {
  const url = new URL(details.url || 'https://app.weavy.ai/');
  if (!['app.weavy.ai', 'api.weavy.ai'].includes(url.hostname)) throw new Error('Cookie URL must be Weavy');
  return chrome.cookies.remove({...details, url: url.href});
}

async function handle(message) {
  const {id, op, params = {}} = message;
  try {
    updateState({backendConnected: true, lastCommand: op, lastError: null});
    let result;
    if (op === 'ping') {
      result = {version: chrome.runtime.getManifest().version, attachedTabId};
    } else if (op === 'tabs.list') {
      result = (await chrome.tabs.query({url: ['https://app.weavy.ai/*']})).map(({id, url, title, active}) => ({id, url, title, active}));
    } else if (op === 'tab.attach') {
      const tab = await ensureAttached(params.tabId || null);
      result = {tabId: tab.id, url: tab.url, title: tab.title, flowId: flowIdFromUrl(tab.url)};
    } else if (op === 'flow.ensure') {
      result = await ensureFlow(params.flowId || null, params.autoCreate !== false);
      if (!result && params.autoCreate !== false) throw new Error('Could not create or select a Weavy flow');
    } else if (op === 'flow.create') {
      const tab = await createFlowFromDashboard();
      result = {tabId: tab.id, title: tab.title, flowId: currentFlowId, flowUrl: tab.url};
    } else if (op === 'flow.current') {
      const tab = attachedTabId === null ? null : await chrome.tabs.get(attachedTabId).catch(() => null);
      const flowId = flowIdFromUrl(tab?.url) || currentFlowId;
      result = flowId ? {flowId, flowUrl: `https://app.weavy.ai/flow/${flowId}`, tabId: tab?.id || null, title: tab?.title || null} : null;
    } else if (op === 'flow.remember') {
      const flowId = normalizeFlowId(params.flowId) || flowIdFromUrl(params.flowUrl);
      if (!flowId) throw new Error('A valid Weavy flow ID or URL is required');
      currentFlowId = flowId;
      updateState({currentFlowId});
      result = {flowId, flowUrl: `https://app.weavy.ai/flow/${flowId}`};
    } else if (op === 'cdp.call') {
      if (BLOCKED_CDP_COOKIE_METHODS.has(params.method)) {
        throw new Error('Use the Weavy-scoped cookies.* bridge operations');
      }
      await ensureAttached(params.tabId || null);
      result = await chrome.debugger.sendCommand({tabId: attachedTabId}, params.method, params.params || {});
    } else if (op === 'events.read') {
      const limit = Math.max(1, Math.min(Number(params.limit || 100), 1000));
      result = eventQueue.splice(0, limit);
    } else if (op === 'cookies.list') {
      result = await cookieList(params.details || {});
    } else if (op === 'cookies.get') {
      const url = new URL(params.url || 'https://app.weavy.ai/');
      if (!['app.weavy.ai', 'api.weavy.ai'].includes(url.hostname)) throw new Error('Cookie URL must be Weavy');
      result = await chrome.cookies.get({url: url.href, name: params.name, storeId: params.storeId});
    } else if (op === 'cookies.set') {
      result = await cookieSet(params);
    } else if (op === 'cookies.remove') {
      result = await cookieRemove(params);
    } else {
      throw new Error(`Unknown bridge operation: ${op}`);
    }
    send({id, result});
  } catch (error) {
    updateState({lastError: error?.message || String(error)});
    send({id, error: {message: error?.message || String(error)}});
  }
}

function connect() {
  if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;
  socket = new WebSocket(BRIDGE_URL);
  socket.onopen = () => {
    updateState({daemonConnected: true, backendConnected: false, lastError: null});
    chrome.action.setBadgeText({text: 'ON'});
    chrome.action.setBadgeBackgroundColor({color: '#16803c'});
    send({event: 'bridge.ready', params: {version: chrome.runtime.getManifest().version}});
  };
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.event === 'daemon.clients') {
        updateState({backendConnected: Number(message.params?.count || 0) > 0});
        return;
      }
      handle(message);
    } catch (error) { send({error: {message: error.message}}); }
  };
  socket.onclose = () => {
    socket = null;
    updateState({daemonConnected: false, backendConnected: false});
    chrome.action.setBadgeText({text: ''});
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1500);
  };
  socket.onerror = () => socket?.close();
}

async function selfTest() {
  const tab = await ensureAttached();
  const evaluated = await chrome.debugger.sendCommand(
    {tabId: tab.id},
    'Runtime.evaluate',
    {expression: '({url:location.href,canvas:Boolean(document.querySelector(".react-flow"))})', returnByValue: true},
  );
  const page = evaluated?.result?.value || {};
  updateState({lastCommand: 'self-test', lastError: null});
  return {ok: true, tab: {id: tab.id, title: tab.title, url: tab.url}, page};
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.op === 'ui.status') {
      let tabs = [];
      try { tabs = await chrome.tabs.query({url: ['https://app.weavy.ai/*']}); } catch {}
      return {...bridgeState, currentFlowId, weavyTabCount: tabs.length, version: chrome.runtime.getManifest().version};
    }
    if (message?.op === 'ui.test') return selfTest();
    if (message?.op === 'ui.openWeavy') {
      const tabs = await chrome.tabs.query({url: ['https://app.weavy.ai/*']});
      if (tabs[0]?.id) {
        await chrome.tabs.update(tabs[0].id, {active: true});
        await chrome.windows.update(tabs[0].windowId, {focused: true});
        return {opened: true, existing: true};
      }
      await chrome.tabs.create({url: 'https://app.weavy.ai/'});
      return {opened: true, existing: false};
    }
    if (message?.op === 'ui.reconnect') {
      connect();
      return {started: true};
    }
    throw new Error('Unknown popup operation');
  })().then(sendResponse).catch((error) => sendResponse({error: error?.message || String(error)}));
  return true;
});

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId !== attachedTabId) return;
  const item = {method, params, timestamp: Date.now()};
  eventQueue.push(item);
  if (eventQueue.length > 2000) eventQueue.shift();
  send({event: 'cdp.event', params: item});
});

chrome.debugger.onDetach.addListener((source, reason) => {
  if (source.tabId === attachedTabId) {
    attachedTabId = null;
    updateState({attachedTabId: null, tabTitle: null, tabUrl: null, lastError: `Debugger detached: ${reason}`});
    send({event: 'cdp.detached', params: {reason}});
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === attachedTabId) {
    attachedTabId = null;
    updateState({attachedTabId: null, tabTitle: null, tabUrl: null});
  }
});

chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.alarms.create('keep-bridge-awake', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === 'keep-bridge-awake') connect(); });
connect();
