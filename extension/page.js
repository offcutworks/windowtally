// Runs in claude.ai's own page, before the page's scripts. It wraps the page's fetch so that whenever the page itself
// receives its organization's usage — on opening the usage settings, and again after each message — the 5-hour and
// weekly figures, and the week's use by product and its per-model weekly windows where the response carries them, are
// handed to relay.js. It sends no request: each response it reads is one the page asked for, read from a clone, so the
// page's own copy is untouched. Nothing else in the response, and no other response, is read.
(() => {
  const USAGE = /^\/api\/organizations\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/usage$/i;
  const KINDS = ["five_hour", "seven_day"];
  const MARK = "windowtally-usage";
  const pageFetch = window.fetch;

  // The week's use by product, as the page's "This week's usage by product" shows it (measured in Chrome on the
  // development machine, 2026-11-02): `seven_day_breakdown` with `as_of`, `window_started_at` and `rows` of `key`,
  // `display_name` and `percent`. It is an addition to the two windows, never a condition of them: a response without
  // it, or with it in another shape, still hands on its windows, and the host checks what is handed on again.
  function byProductOf(body) {
    const breakdown = body && body.seven_day_breakdown;
    if (!breakdown || !Array.isArray(breakdown.rows) || !breakdown.rows.length) return null;
    return {
      asOf: breakdown.as_of,
      windowStartedAt: breakdown.window_started_at,
      rows: breakdown.rows.map((row) => (
        { key: row && row.key, name: row && row.display_name, percent: row && row.percent })),
    };
  }

  // The week's per-model windows, as the page's usage settings show Fable's beside the weekly window (measured in
  // Chrome on the development machine, 2026-11-10): `limits` rows of kind `weekly_scoped` naming their model in
  // `scope.model.display_name`, with `percent` and `resets_at`; and `weekly_scoped_shares`, whose rows give, by the
  // limit's index in `limits` (`limit_index`), the window's allowance as a share of the weekly window
  // (`allowance_percent_of_weekly`). An addition to the two windows, never a condition of them, which the host checks
  // again.
  function scopedOf(body) {
    const limits = body && Array.isArray(body.limits) ? body.limits : [];
    const shares = body && Array.isArray(body.weekly_scoped_shares) ? body.weekly_scoped_shares : [];
    const rows = [];
    limits.forEach((limit, index) => {
      const model = limit && limit.kind === "weekly_scoped" && limit.scope && limit.scope.model;
      if (!model || typeof model.display_name !== "string") return;
      const share = shares.find((row) => row && row.limit_index === index);
      const allowance = share && share.allowance_percent_of_weekly;
      rows.push({
        name: model.display_name,
        percentUsed: limit.percent,
        resetsAt: typeof limit.resets_at === "string" ? limit.resets_at : null,
        allowanceOfWeekly: typeof allowance === "number" ? allowance : null,
      });
    });
    return rows;
  }

  function windowsOf(body) {
    const windows = [];
    for (const kind of KINDS) {
      const figure = body && body[kind];
      if (figure && typeof figure.utilization === "number" && Number.isFinite(figure.utilization)) {
        windows.push({
          kind,
          percentUsed: figure.utilization,
          resetsAt: typeof figure.resets_at === "string" ? figure.resets_at : null,
        });
      }
    }
    return windows;
  }

  function observe(request, response) {
    const t = Date.now();
    let url;
    try {
      url = new URL(request instanceof Request ? request.url : String(request), location.href);
    } catch {
      return;
    }
    const match = url.origin === location.origin && USAGE.exec(url.pathname);
    if (!match || !response.ok) return;
    response.clone().json().then((body) => {
      const windows = windowsOf(body);
      if (windows.length) {
        const reading = { [MARK]: 1, org: match[1].toLowerCase(), t, windows };
        const byProduct = byProductOf(body);
        if (byProduct) reading.weeklyByProduct = byProduct;
        const scoped = scopedOf(body);
        if (scoped.length) reading.weeklyScoped = scoped;
        window.postMessage(reading, location.origin);
      }
    }, () => {});
  }

  window.fetch = function (...args) {
    const answer = pageFetch.apply(this, args);
    answer.then((response) => {
      try {
        observe(args[0], response);
      } catch {
        // The page's own fetch is never disturbed by a failure here.
      }
    }, () => {});
    return answer;
  };
})();
