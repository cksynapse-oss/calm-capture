/**
 * Calm Capture — service-worker.js  (Chrome MV3 background service worker)
 *
 * Responsibilities:
 *  1. Manage a persistent Native Messaging connection to com.corteon.capture
 *  2. Handle the 'capture' keyboard command (Cmd/Ctrl+Shift+K)
 *  3. Forward tab URL/title changes to the native host as tab_context messages
 *  4. Relay trigger_capture messages from the native host to the active tab
 *  5. Reconnect automatically when the native port is closed
 */

'use strict';

/* ─────────────────────────────────────────────────────────────────────────
 * CONSTANTS
 * ───────────────────────────────────────────────────────────────────────── */

const NATIVE_HOST = 'com.corteon.capture';

/** How long to wait before attempting a reconnect after the port closes (ms). */
const RECONNECT_DELAY_MS = 2000;

/** Maximum reconnect delay (exponential back-off ceiling). */
const MAX_RECONNECT_DELAY_MS = 30_000;

/** Heartbeat interval — keeps the service worker alive while connected (ms). */
const HEARTBEAT_INTERVAL_MS = 20_000;

/* ─────────────────────────────────────────────────────────────────────────
 * STATE
 * ───────────────────────────────────────────────────────────────────────── */

/** @type {chrome.runtime.Port | null} */
let nativePort = null;

/** Whether we are currently attempting to connect (prevents stampede). */
let connecting = false;

/** Current back-off delay for reconnection attempts. */
let reconnectDelay = RECONNECT_DELAY_MS;

/** Timer IDs so we can cancel them cleanly. */
let heartbeatTimer = null;
let reconnectTimer = null;

/** Track the last known active tab so we can send tab_context immediately. */
let lastTabContext = { url: '', title: '' };

/* ─────────────────────────────────────────────────────────────────────────
 * NATIVE MESSAGING — CONNECTION MANAGEMENT
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Open (or re-open) the native messaging port.
 * Idempotent — safe to call when already connected.
 */
function connectNative() {
  if (connecting || (nativePort !== null)) return;

  connecting = true;

  try {
    nativePort = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (err) {
    console.error('[CalmCapture] connectNative threw:', err);
    nativePort = null;
    connecting = false;
    scheduleReconnect();
    return;
  }

  connecting = false;

  console.log('[CalmCapture] Native port opened');

  // Persist connection status for popup
  chrome.storage.local.set({ nativeConnected: true });

  // Start heartbeat
  startHeartbeat();

  // Reset back-off on successful connect
  reconnectDelay = RECONNECT_DELAY_MS;

  nativePort.onMessage.addListener(handleNativeMessage);

  nativePort.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError;
    if (err) {
      console.warn('[CalmCapture] Native port disconnected:', err.message);
    } else {
      console.log('[CalmCapture] Native port disconnected (clean)');
    }

    nativePort = null;
    stopHeartbeat();
    chrome.storage.local.set({ nativeConnected: false });
    scheduleReconnect();
  });

  // Send the current tab context immediately so the daemon is in sync
  sendTabContextToNative(lastTabContext.url, lastTabContext.title);
}

/**
 * Schedule a reconnection attempt after the current back-off delay.
 */
function scheduleReconnect() {
  if (reconnectTimer !== null) return; // already scheduled

  console.log(`[CalmCapture] Reconnecting in ${reconnectDelay}ms`);

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectNative();
  }, reconnectDelay);

  // Exponential back-off with ceiling
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
}

/**
 * Send a message to the native host. Silently ignores if not connected.
 */
function sendToNative(payload) {
  if (!nativePort) {
    console.warn('[CalmCapture] sendToNative: no port, queuing reconnect');
    connectNative();
    return false;
  }
  try {
    nativePort.postMessage(payload);
    return true;
  } catch (err) {
    console.error('[CalmCapture] sendToNative error:', err);
    return false;
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * HEARTBEAT — keeps the service worker alive while a native port is open
 * ───────────────────────────────────────────────────────────────────────── */

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (!nativePort) {
      stopHeartbeat();
      return;
    }
    try {
      nativePort.postMessage({ type: 'Heartbeat', payload: { ts: Date.now() } });
    } catch (_) {
      stopHeartbeat();
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat() {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * NATIVE MESSAGE HANDLER
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Handle messages arriving from the native host process.
 *
 * Supported actions from native host:
 *   { action: 'trigger_capture' }  — the daemon wants to capture the active tab
 *   { action: 'ping' }             — health check; we reply with pong
 */
async function handleNativeMessage(message) {
  console.log('[CalmCapture] Message from native:', message);

  if (!message || typeof message !== 'object') return;

  switch (message.type) {
    case 'TriggerCapture': {
      await captureActiveTab();
      break;
    }

    case 'Ping': {
      sendToNative({ type: 'Pong', payload: { ts: Date.now() } });
      break;
    }

    default:
      console.warn('[CalmCapture] Unknown native action:', message.type);
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * CAPTURE FLOW
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Inject the content script into the active tab (if not already injected),
 * send the 'extract' message, and relay the result to the native host.
 */
async function captureActiveTab() {
  let tab;
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    tab = activeTab;
  } catch (err) {
    console.error('[CalmCapture] Could not query active tab:', err);
    return;
  }

  if (!tab || !tab.id) {
    console.warn('[CalmCapture] No active tab found');
    return;
  }

  // Check if tab URL is injectable (cannot inject into chrome:// etc.)
  const url = tab.url || '';
  if (!url || url.startsWith('chrome://') || url.startsWith('chrome-extension://') ||
      url.startsWith('about:') || url.startsWith('data:') || url.startsWith('edge://')) {
    console.warn('[CalmCapture] Tab is not injectable:', url);
    sendToNative({
      type: 'CaptureError',
      payload: { error: 'Cannot capture this page type', url }
    });
    return;
  }

  // Ensure content script is running (it may not be on tabs that were open before the extension installed)
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content-script.js'],
    });
  } catch (_) {
    // Already injected — ignore the error
  }

  // Ask content script to extract
  let result;
  try {
    result = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('content-script timeout')), 15_000);
      chrome.tabs.sendMessage(tab.id, { action: 'extract' }, (response) => {
        clearTimeout(timeout);
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else {
          resolve(response);
        }
      });
    });
  } catch (err) {
    console.error('[CalmCapture] Content script error:', err);
    sendToNative({
      type: 'CaptureError',
      payload: { error: err.message, url }
    });
    return;
  }

  if (!result) {
    sendToNative({ type: 'CaptureError', payload: { error: 'No response from content script', url } });
    return;
  }

  if (!result.success) {
    sendToNative({ type: 'CaptureError', payload: { error: result.error, url } });
    return;
  }

  // Relay to native host
  sendToNative({
    type: 'CaptureResult',
    payload: {
      capture_id: crypto.randomUUID(),
      title: result.title,
      content_markdown: result.content_markdown,
      byline: result.byline || null,
      excerpt: result.excerpt,
      source_url: result.source_url,
      word_count: result.word_count,
      timestamp: new Date().toISOString()
    }
  });

  console.log('[CalmCapture] Capture relayed to native host:', result.title);
}

/* ─────────────────────────────────────────────────────────────────────────
 * TAB CONTEXT TRACKING
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Send tab_context to native host.
 */
function sendTabContextToNative(url, title) {
  if (!url) return;
  sendToNative({
    type: 'TabContext',
    payload: {
      url,
      title: title || ''
    }
  });
}

/**
 * Called whenever the active tab or its URL/title changes.
 */
function onTabContextChanged(tabId, changeInfo, tab) {
  // Only fire when the URL has committed (not on loading start)
  if (changeInfo && changeInfo.status && changeInfo.status !== 'complete') return;

  const url = tab?.url || '';
  const title = tab?.title || '';

  if (url === lastTabContext.url && title === lastTabContext.title) return;

  lastTabContext = { url, title };
  sendTabContextToNative(url, title);
}

/* ─────────────────────────────────────────────────────────────────────────
 * EVENT LISTENERS
 * ───────────────────────────────────────────────────────────────────────── */

// Keyboard shortcut from Chrome
chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'capture') {
    console.log('[CalmCapture] Hotkey triggered');
    await captureActiveTab();
  }
});

// Tab updates — URL / title changes
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // Only care about the active tab
  if (!tab.active) return;
  onTabContextChanged(tabId, changeInfo, tab);
});

// Tab activation (user switches tabs)
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    onTabContextChanged(tabId, null, tab);
  } catch (_) { /* tab may have closed */ }
});

// Window focus change — update context when user switches windows
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, windowId });
    if (tab) onTabContextChanged(tab.id, null, tab);
  } catch (_) { /* ignore */ }
});

// Messages from popup or other extension pages
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message !== 'object') return false;

  switch (message.action) {
    case 'get_status': {
      sendResponse({
        nativeConnected: nativePort !== null,
        lastTabContext,
      });
      return false; // synchronous response
    }

    case 'manual_capture': {
      captureActiveTab().then(() => sendResponse({ ok: true })).catch((err) => {
        sendResponse({ ok: false, error: err.message });
      });
      return true; // async
    }

    case 'reconnect_native': {
      if (!nativePort) connectNative();
      sendResponse({ ok: true });
      return false;
    }

    default:
      return false;
  }
});

// Service worker install / activate
self.addEventListener('install', () => {
  console.log('[CalmCapture] Service worker installed');
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('[CalmCapture] Service worker activated');
  event.waitUntil(clients.claim());
});

/* ─────────────────────────────────────────────────────────────────────────
 * STARTUP
 * ───────────────────────────────────────────────────────────────────────── */

// Attempt native connection on startup
connectNative();

// Sync initial tab context
(async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      lastTabContext = { url: tab.url || '', title: tab.title || '' };
    }
  } catch (_) { /* ignore */ }
})();
