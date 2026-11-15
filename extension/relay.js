// Carries page.js's figures from claude.ai's page to the extension's service worker. page.js runs in the page's own
// world, which has no extension API; this script runs beside it in the extension's. Only a message posted by this
// very page in page.js's shape is passed on, and the native host checks it again before anything is written.
const MARK = "windowtally-usage";

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== location.origin) return;
  const data = event.data;
  if (!data || data[MARK] !== 1) return;
  const reading = { org: data.org, t: data.t, windows: data.windows };
  if (data.weeklyByProduct !== undefined) reading.weeklyByProduct = data.weeklyByProduct;
  if (data.weeklyScoped !== undefined) reading.weeklyScoped = data.weeklyScoped;
  try {
    chrome.runtime.sendMessage(reading).catch(() => {});
  } catch {
    // The extension was reloaded or removed while the page stayed open: the page goes on unchanged.
  }
});
