// Hands each reading relay.js sends to WindowTally's native host, which writes it where WindowTally's service reads it. Chrome
// starts the host for each message and ends it after the answer; the extension opens no other connection of any kind.
const HOST = "windowtally.browser";
const VERSION = 1;

// The week's use by product and its per-model windows ride the same version as optional keys: a host that does not
// know one builds its file from the keys it checks and drops it, and this host drops one alone, keeping the windows,
// when it is not in the shape the host writes, and says so in its answer.
chrome.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== chrome.runtime.id || sender.origin !== "https://claude.ai") return;
  const reading = { v: VERSION, org: message.org, t: message.t, windows: message.windows };
  if (message.weeklyByProduct !== undefined) reading.weeklyByProduct = message.weeklyByProduct;
  if (message.weeklyScoped !== undefined) reading.weeklyScoped = message.weeklyScoped;
  chrome.runtime.sendNativeMessage(HOST, reading)
    .then((answer) => {
      if (!answer || !answer.ok) console.warn("WindowTally: the host refused a reading:", answer && answer.error);
      else if (answer.dropped) {
        console.warn("WindowTally: the host kept the windows and left out:", answer.dropped);
      }
    }, (error) => {
      console.warn("WindowTally: the host could not be reached; run install.ps1 -Mode Install.", error.message);
    });
});
