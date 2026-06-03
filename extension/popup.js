/**
 * Calm Capture — popup.js
 *
 * Queries the service worker for connection status, updates the UI,
 * and wires up the "Capture now" and "Reconnect" buttons.
 */

'use strict';

/* ─────────────────────────────────────────────────────────────────────────
 * DOM REFERENCES
 * ───────────────────────────────────────────────────────────────────────── */

const statusCard  = document.getElementById('statusCard');
const statusDot   = document.getElementById('statusDot');  // kept for reference; card class drives CSS
const statusLabel = document.getElementById('statusLabel');
const statusSub   = document.getElementById('statusSub');
const btnCapture  = document.getElementById('btnCapture');
const btnReconnect= document.getElementById('btnReconnect');
const modKey      = document.getElementById('modKey');
const toast       = document.getElementById('toast');

/* ─────────────────────────────────────────────────────────────────────────
 * PLATFORM KEY LABEL
 * ───────────────────────────────────────────────────────────────────────── */

// navigator.platform is deprecated but still reliable for this narrow use-case
const isMac = /mac/i.test(navigator.platform) || /mac/i.test(navigator.userAgent);
modKey.textContent = isMac ? '⌘' : 'Ctrl';

/* ─────────────────────────────────────────────────────────────────────────
 * STATUS RENDERING
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Apply connected / disconnected UI state.
 * @param {boolean} connected
 * @param {string} [url]
 */
function renderStatus(connected, url) {
  statusCard.classList.toggle('connected', connected);
  statusCard.classList.toggle('disconnected', !connected);

  if (connected) {
    statusLabel.textContent = 'Calm Capture active';
    if (url && url !== '' && !url.startsWith('chrome://') && !url.startsWith('about:')) {
      const short = truncateUrl(url, 42);
      statusSub.textContent = short;
    } else {
      statusSub.textContent = 'Daemon connected';
    }
  } else {
    statusLabel.textContent = 'Daemon disconnected';
    statusSub.textContent = 'Click ↻ to reconnect';
  }
}

/**
 * Truncate a URL to maxLen characters, keeping the domain visible.
 */
function truncateUrl(url, maxLen) {
  try {
    const u = new URL(url);
    const short = u.hostname + u.pathname;
    if (short.length <= maxLen) return short;
    return short.slice(0, maxLen - 1) + '…';
  } catch (_) {
    if (url.length <= maxLen) return url;
    return url.slice(0, maxLen - 1) + '…';
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * TOAST NOTIFICATIONS
 * ───────────────────────────────────────────────────────────────────────── */

let toastTimer = null;

/**
 * Show a brief toast message.
 * @param {string} msg
 * @param {'ok'|'err'} type
 * @param {number} [durationMs]
 */
function showToast(msg, type, durationMs = 2800) {
  if (toastTimer) clearTimeout(toastTimer);

  toast.textContent = msg;
  toast.className = type;
  toast.style.display = 'block';
  toast.style.opacity = '1';

  toastTimer = setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => { toast.style.display = 'none'; }, 200);
    toastTimer = null;
  }, durationMs);
}

/* ─────────────────────────────────────────────────────────────────────────
 * QUERY SERVICE WORKER STATUS
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * Ask the background service worker for current connection status.
 * Falls back to chrome.storage.local if the SW is not yet ready.
 */
async function fetchStatus() {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ action: 'get_status' }, (response) => {
        if (chrome.runtime.lastError || !response) {
          // SW may have been terminated — fall back to storage
          chrome.storage.local.get(['nativeConnected'], (result) => {
            resolve({
              nativeConnected: result.nativeConnected === true,
              lastTabContext: { url: '', title: '' },
            });
          });
          return;
        }
        resolve(response);
      });
    } catch (err) {
      resolve({ nativeConnected: false, lastTabContext: { url: '', title: '' } });
    }
  });
}

async function refreshStatus() {
  const status = await fetchStatus();
  renderStatus(status.nativeConnected, status.lastTabContext?.url || '');
  checkTabType();
}

/**
 * Inspect the active tab to show helper tips if Chrome restrictions block content script scraping (e.g. PDFs, system pages).
 */
function checkTabType() {
  try {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (chrome.runtime.lastError || !tabs || tabs.length === 0) return;
      const activeTab = tabs[0];
      if (!activeTab || !activeTab.url) return;

      const url = activeTab.url.toLowerCase();
      const isPDF = url.endsWith('.pdf') || url.includes('.pdf?') || url.includes('/pdf/') || (url.startsWith('chrome-extension://') && url.includes('pdf'));
      const isRestricted = url.startsWith('chrome://') || (url.startsWith('chrome-extension://') && !url.includes('pdf')) || url.startsWith('edge://') || url.startsWith('about:');

      const tipCard = document.getElementById('tipCard');
      const tipTitle = document.getElementById('tipTitle');
      const tipDesc = document.getElementById('tipDesc');

      if (tipCard) {
        if (isPDF || isRestricted) {
          tipCard.style.display = 'block';
          if (tipTitle) {
            tipTitle.textContent = isPDF ? 'PDF Document Detected' : 'System Page Restricted';
          }
          if (tipDesc) {
            tipDesc.innerHTML = isPDF
              ? `Chrome blocks extension scripts on PDFs. Use <b style="color: var(--accent); font-family: monospace;">Cmd+Shift+K</b> to capture with native Screen OCR!`
              : `Chrome restricts scripts on system pages. Use <b style="color: var(--accent); font-family: monospace;">Cmd+Shift+K</b> to capture with native Screen OCR!`;
          }
        } else {
          tipCard.style.display = 'none';
        }
      }
    });
  } catch (_) {}
}

/* ─────────────────────────────────────────────────────────────────────────
 * BUTTON HANDLERS
 * ───────────────────────────────────────────────────────────────────────── */

btnCapture.addEventListener('click', async () => {
  btnCapture.disabled = true;
  btnCapture.textContent = 'Capturing…';

  try {
    const result = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: 'manual_capture' }, (resp) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
        } else {
          resolve(resp || { ok: false, error: 'No response' });
        }
      });
    });

    if (result.ok) {
      showToast('Captured! Sent to daemon.', 'ok');
    } else {
      showToast(result.error || 'Capture failed', 'err');
    }
  } catch (err) {
    showToast(err.message || 'Unexpected error', 'err');
  } finally {
    btnCapture.disabled = false;
    btnCapture.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M6 1v10M1 6h10" stroke="white" stroke-width="1.8" stroke-linecap="round"/>
      </svg>
      Capture now`;
    // Refresh status after capture attempt
    await refreshStatus();
  }
});

btnReconnect.addEventListener('click', async () => {
  btnReconnect.disabled = true;
  try {
    await new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: 'reconnect_native' }, () => resolve());
    });
    // Give the SW a moment to connect before we re-query
    await new Promise(r => setTimeout(r, 800));
    await refreshStatus();
    showToast('Reconnect requested', 'ok', 1800);
  } finally {
    btnReconnect.disabled = false;
  }
});

/* ─────────────────────────────────────────────────────────────────────────
 * LIVE STORAGE LISTENER
 * Updates the popup in real time if the native port connects/disconnects
 * while the popup is open (rare, but correct).
 * ───────────────────────────────────────────────────────────────────────── */

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if ('nativeConnected' in changes) {
    const connected = changes.nativeConnected.newValue === true;
    renderStatus(connected, '');
    // Also fetch tab context
    refreshStatus();
  }
});

/* ─────────────────────────────────────────────────────────────────────────
 * INITIALISE
 * ───────────────────────────────────────────────────────────────────────── */

// Immediately render a neutral state, then query the SW
renderStatus(false, '');
statusSub.textContent = 'Checking daemon…';

refreshStatus();
checkTabType();
