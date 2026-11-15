# WindowTally — design record

What the tool is built to do, how its parts meet, which contracts they share, and the decisions behind them.
The module docstrings are the canonical statement of each contract; this file maps them and records why.

## Purpose

WindowTally serves one person who uses several Claude subscription accounts on one Windows machine, in the Claude
desktop app's Code tab and the Claude Code CLI, and moves between them as their limits fill. It answers, at a glance
and without polling anything: where does each account stand in its 5-hour and weekly windows, which account should be
used next, and — kept permanently — what each account was used for (sessions, prompts, models, effort, tokens,
API-equivalent cost). From the user's own bills it also learns which plan each account held when and sets that
against the account's use: the plans' cost per month at their US list price; how far each account is paid up; and
each plan period's API-equivalent use beside its cost at list price. Outside Claude Code the WindowTally window shows
the same standings live, in a desktop window and a tray icon, with WindowTally's actions and the user's bills a click
away, and the whole history over a span the user chooses. From the window the user also switches the desktop app, and
the CLI, from one account to another with a click, a switch of the app taking along to the other account the Code
sessions the user chooses of the account it leaves, and finds every account's Code sessions in one list, from which
one opens on the account in use.

## Parts and processes

| Part | Where it runs | Owns |
|---|---|---|
| Account sync (`sync/WindowTallySync.ps1`, `sync/claude.cmd`) | its own logon task `\WindowTally\Sync`, from `%USERPROFILE%\.claude\bin`; and as a process of its own whenever the window asks it to switch, to turn a switch or to start the desktop app | the CLI's sign-in: it swaps stored, DPAPI-sealed credentials so the CLI follows the desktop app's account; the desktop app's login (two values of its `config.json` and its `Network\Cookies` file), stored per account and put back to switch the app, and cleared, with nothing sent to the server, to add an account; the two switches `sync-settings.json`; publishes `events.jsonl` and `watch.json` |
| Ledger service (`windowtally/`) | its own logon task `\WindowTally\Service`, from `%USERPROFILE%\.claude\windowtally\app` | `ledger.sqlite3`, `status.json`, `dashboard.html`, `service.log`; reads every source and writes none, except that its command line writes the user's `bills.json` and `settings.json` on the user's command; the service alone holds a Windows power request that keeps the system awake while Claude Code's session registry names a session at work and the user's setting allows it |
| Desktop plugin (`plugin/`) | inside each Claude Code session (desktop Code tab, CLI), installed at user scope from its copy `%USERPROFILE%\.claude\windowtally\plugin`, the folder marketplace `windowtally-local` | writes plan readings; draws the status band and panel from `status.json`; raises the limit warnings unless `status.json` says the user silenced WindowTally's notifications, keeping the crossings already warned of, and the desktop band's fold, in its Claude Code store; on its panel's window button, asks the window to show itself through `window.request`, or has Task Scheduler run the window's logon task |
| Browser extension (`extension/`) and its native-messaging host (`windowtally/browser_host.py`), optional | the extension in Chrome, loaded unpacked by the user from its copy `%USERPROFILE%\.claude\windowtally\extension`; the host started by Chrome for each message, through the launcher in `%USERPROFILE%\.claude\windowtally\browser-host`, under the console interpreter on the service's installed copy | the extension reads the 5-hour and weekly figures of the usage responses claude.ai's own page receives, and the week's use by product and its per-model weekly windows (Fable's) where a response carries them, sends no request and reads no credential, and hands each reading to the host through Chrome's native messaging; the host checks it whole, the use by product and the per-model windows each on its own, and writes `browser\<organizationUuid>.json`; `python -m windowtally browser register`, run by `install.ps1` from a one-off task, writes the launcher, the host's manifest and the one key `HKCU\Software\Google\Chrome\NativeMessagingHosts\windowtally.browser`. WindowTally stands whole without them |
| Window (`windowtally_gui/`) | its own logon task `\WindowTally\Window`, started into the tray, from `%USERPROFILE%\.claude\windowtally\app` beside the service's copy; by hand from its Start menu entry, which its own code writes, with the logo drawn into `windowtally.ico` beside the packages, from the one-off task `\WindowTally\Setup` | `window.json`, `window.log`; shows `status.json` and opens the ledger read-only; on the user's command runs a pass and writes the user's `bills.json` and `settings.json`, through the ledger service's own functions, and the History window's export where the user saves it; starts the account sync as a process of its own to switch an account, turn one of its two switches or start the desktop app, and counts and names the sessions at work off Claude Code's session registry before it closes the desktop app; writes the keep-awake's switch into `settings.json`, which the service reads; at a switch of the desktop app offers the sessions of the account it leaves, read from the ledger, and opens those chosen through the app's resume link once the switch is done, writing nothing of the app's own; lists every account's Code sessions in the Conversations window, read from the ledger, and opens one through the same link or copies its resume command; raises the desktop notifications, none while the user's setting silences them |

The sync and the ledger are separate processes on purpose: the code that handles credentials never shares a
process with the code that parses every transcript, and the ledger only reads what the sync publishes. The
window keeps the rule: it never touches a credential, it starts the sync, as a process of its own, to switch an
account, and reads the notes and the exit code the sync answers with.
Dependencies run one way — the ledger reads the sync's records, the plugin's readings, the browser extension's
readings as its host writes them, and the user's bills; the
plugin reads the ledger's `status.json`; the window reads `status.json` too, imports the ledger service's package for
every figure, rule and write, and opens the ledger read-only for the accounts' colours, the History window's history
and the sessions a switch offers and the Conversations window lists, through that package's own code. The history
page, the History window and the file it exports draw one figures layer (`windowtally/history.py`), the page and the
export adding only their markup (`windowtally/dashboard.py`), the window its widgets. The service never imports the
window, and nothing outside the service's own package reads the ledger's internals.

## Sources (formats as measured on the development machine, 2026-10-20, Claude Code 2.1.299)

- **Transcripts**, `~/.claude/projects/**/*.jsonl` — `ingest_transcripts`. One line per content block; all lines of
  one response repeat its `message.id` and the usage known so far (the last carries the final usage). Desktop
  sessions write `bridge-session` lines naming the owning account, and that name lags the desktop app: sessions
  opened after the app switched account went on naming the old one, while the plan figures that rose with their use
  were the new account's (measured on the development machine, 2026-09-21 to 2026-10-21), so attribution takes it
  only before the timelines begin. The first pass reads every transcript whole; each later pass reads a file only
  from where the last one stopped, and a file that shrank from the start again. Measured on the development machine,
  2026-11-08, Claude Code 2.1.308 and 2.1.310: a session's title stands in `custom-title` lines (`customTitle`, the
  title the desktop app shows, written again as it changes) and `ai-title` lines (`aiTitle`, the one Claude Code makes
  up itself), which carry no time, so of two lines the later stands, and a `custom-title` stands before an `ai-title`;
  every card the app kept but one showed its transcript's last `custom-title`. A subagent's transcript holds no title
  line. A turn a plan limit refused is an assistant line flagged `isApiErrorMessage` with `error` `rate_limit` (HTTP
  429), whose text says the session or weekly limit was hit, as every such line read then did; from
  Claude Code 2.1.299 it also carries `quotaLimits`, and `apiErrorParams.rate_limit_info`, naming the window,
  `rateLimitType` `five_hour` or `seven_day`, and its reset, `resetsAt` in epoch seconds. Only a main session's
  stop is recorded, a subagent's being its parent's turn's. Measured on the development machine, 2026-11-10, Claude
  Code 2.1.280 to 2.1.310: a main session starts a background task on a tool result — a command's carries
  `toolUseResult.backgroundTaskId`, a subagent's `toolUseResult.status` `async_launched` beside its `agentId` — and the
  task's end is a notification, text that names the task (`<task-id>`) and how it ended (`<status>`: completed, failed
  or stopped), written as a `queue-operation` line of `operation` `enqueue` when the task ends and, to an idle
  session, as a user line of `origin.kind` `task-notification`; a task the session stops itself ends on that tool
  result instead, `toolUseResult.task_id` under a `message` that opens *Successfully stopped task*. All but a few of
  the commands started in the background had a notification queued or were stopped by their session, and all but a
  few subagents had one. A notification with no `<status>` is an event of a task that watches, which is not read. The
  end of a task whose session's process had gone was written into the transcript the session went on in, so an end is
  matched by the task's id whatever transcript holds it. Background tasks are not caught up as titles and stops were:
  only those of the last day are ever asked for. A prompt's line names `permissionMode`, the permission mode its turn
  runs in, and a `permission-mode` line, written as the mode changes and carrying no time, names it too, so a main
  session's mode is the one its transcript names last; a subagent's transcript is not read for it (measured on the
  development machine, 2026-11-11, over the main transcripts of Claude Code 2.1.269 to 2.1.321: the modes named were
  `auto`, `acceptEdits`, `default`, `bypassPermissions` and `plan`). The
  ledger records which kinds of line every transcript has been read for (its meta key `transcript_kinds`): a ledger
  read for fewer than the code reads has the part already read of each main transcript read once more, for titles,
  limit stops and permission modes alone, before any new line, rather than having every response read and written
  again. A file that cannot be read leaves that catch-up to the next pass, a title it reads replaces only one Claude
  Code made up, and only with the app's, and a mode it reads stands only where the session has none, so a catch-up run
  again puts no older title or mode back. Measured on the development machine,
  2026-11-09, Claude Code 2.1.308 and 2.1.310: the working folder a line names, `cwd`, moves with every change of
  directory the session makes, so its first main answer names the folder it was started in; a subagent's lines carry
  their session's `entrypoint` (`claude-desktop` for the desktop app's Code tab, `cli` for the CLI); and no transcript
  names another as the one it goes on from or into — no `continued-in` or `forkedFrom` line — while some of the app's
  session cards name earlier transcripts of their own.
- **Desktop app usage history**, `%APPDATA%\Claude\plan-usage-history.json` (version 2) — `ingest_app_history`. The
  signed-in account's 5-hour and weekly percentages, about every 15 minutes while the app runs, kept about 30 days,
  no reset times. Its sampling pauses for hours while the app runs, so it is history, not a live source.
- **Plugin readings**, `%USERPROFILE%\.claude\windowtally\readings\<sessionId>.json` (version 1) — `ingest_readings`.
- **Browser readings**, `%USERPROFILE%\.claude\windowtally\browser\<organizationUuid>.json` (version 1) —
  `ingest_browser`, written by the browser extension's host (`browser_host`), one file per organization holding its
  latest reading. What claude.ai's page receives, measured in Chrome on the development machine, 2026-10-29, reading
  only what the page itself requested: the page asks for `GET /api/organizations/<organizationUuid>/usage` when its
  usage settings open, and asked again after a chat message was sent (seen once, for one message); the response's
  `five_hour` and `seven_day` each carry `utilization`, a whole-number percentage, and `resets_at`, an ISO 8601 time
  with microseconds and an explicit offset, among other keys the extension does not read. Measured on the development
  machine, 2026-11-02, in a browser and again reading only what the page itself requested, the response also carries
  `seven_day_breakdown`, the split the usage page shows under *This week's usage by product*: `as_of`, when claude.ai
  computed it, and `window_started_at`, the start of the weekly window it covers, both times written as `resets_at`
  is, and `rows`, each a product's `key` (`claude_code`, `chat`, `cowork`, `other`), the `display_name` the page shows
  for it (Claude Code, Chats, Cowork, Other) and its `percent`, a whole number, in the page's order; the page's section
  showed exactly those rows. Two responses for one window named starts less than a second apart. Measured on the
  development machine, 2026-11-10, in Chrome, again reading only what the page itself requested: the response also
  carries `limits`, a list of rows by `kind` — `weekly_all`, the weekly window, and `weekly_scoped`, a model's own
  window inside it, naming the model in `scope.model.display_name` (Fable), with its `percent` and `resets_at`, the
  week's reset — and `weekly_scoped_shares`, whose row for that limit (`limit_index` 1) gives `used_percent_of_weekly`
  and `allowance_percent_of_weekly`, the model's allowance, half the weekly window on the plan it was read on; the page
  also asked for the same path with a query string, which the extension matches by its path alone. Claude Code hands
  its plugins no such window: the rate limits a plugin receives are built from the 5-hour and weekly windows and a
  gateway's spend limit alone (the desktop app's build 2.1.321, read the same day). The request is the page's own,
  not an interface claude.ai offers, and an update of the site can change it (*Caveats*).
- **Sync records**, `~/.claude/accounts/` — `accounts` (the `oauthAccount.json` profiles; the sealed credentials
  beside them are never opened), `ingest_sync` (`events.jsonl`, the older `sync.log`, `watch.json`), `sync_store`
  (`sync-settings.json`, the sync's two switches; and, beside an account's profile, whether its `desktop-login.dpapi`
  exists: the stored desktop login is never opened).
- **Claude Code's session registry**, `%USERPROFILE%\.claude\sessions\<pid>.json` — `registry`; read by the service,
  the window and the sync's `Status`. Measured on the development machine, 2026-11-11, the CLI's build 2.1.310 and the
  desktop app's 2.1.321: every running Claude Code process keeps one file named after its process id, written by both
  builds, which it removes when it ends; a scripted `-p` run's file (`entrypoint` `sdk-cli`) appeared at its start,
  read `busy` while it ran and was gone after its end, and a desktop process's file stood about two seconds without
  a `status` before its first report. The fields read are `pid`; `sessionId`, the transcript's own; `procStart`, the
  process's creation time as a decimal Windows FILETIME, equal on every live file to the creation time Windows gives
  (`GetProcessTimes`, and PowerShell's `Get-Process` alike), which the 2.1.310 binary also reads as `procStartFt`;
  `entrypoint`, `claude-desktop` for a session the desktop app hosts; `status`; and `statusUpdatedAt`, epoch
  milliseconds, written only when `status` changes. Read statically from the 2.1.310 binary, the terminal UI writes
  `status` from its own turn state: `waiting` while a dialog or a question waits on the person, else `busy` while a turn
  loads or work it delegated runs, else `idle`, written `shell` when idle with a background shell left running; and it
  holds a sleep inhibitor of its own while busy, which on Windows does nothing (it starts `caffeinate` on macOS only).
  Every other field — `cwd`, `startedAt`, `version`, `kind`, `name`, `updatedAt` and more — is left alone, and the
  `<pid>.<hash>.key` files beside them, which may hold secrets, are never opened. At one look every desktop session's
  `busy` or `idle` agreed with whether its transcript's latest turn had ended, and a turn a background task's
  notification started read `busy` within its first second. A terminal session's file during a turn was not observed.
  `powercfg /requests` during a desktop turn listed the desktop app's process under EXECUTION and nothing under
  DISPLAY.
- **Bills**, the user's own — `bills`: `bills.json` in WindowTally's data folder (version 1), and each further bill
  file `settings.json` (version 1) lists, in the same format or a bill archive's manifest (`bills_manifest`). Nothing
  else on the machine says what a subscription cost: an account's profile names only the plan it is on now. Every source
  is read in full on every pass and copied nowhere.
- Not read by the service or the window: the desktop app's `config.json` (it holds OAuth tokens; the sync reads and
  writes two of its values and its sign-in mark to switch the app's login and to add an account); the agent-mode
  sessions under `%APPDATA%\Claude\local-agent-mode-sessions`.
- **The desktop app's login**, read and written by the sync alone, measured on the development machine, 2026-10-25:
  `%APPDATA%\Claude\config.json` holds it in the string values `oauth:tokenCacheV2` and `lastKnownAccountUuid` (each
  once, at the top level, beside an older `oauth:tokenCache` and per-organisation `dxt:*` keys that are not touched),
  and `%APPDATA%\Claude\Network\Cookies` (SQLite, with a `Cookies-journal` beside it) holds the session
  cookies, locked while the app runs. The app's feature flags are cached in the file `%APPDATA%\Claude\fcache`. The app
  is the MSIX package `Claude_pzs8sxrjxfjjc`, its processes running from `C:\Program Files\WindowsApps\Claude_<version>_x64__pzs8sxrjxfjjc\app`,
  started through the Start menu entry `Claude_pzs8sxrjxfjjc!Claude`; the Claude Code engines it hosts run from
  `%APPDATA%\Claude\claude-code\<version>` and are not the app's own processes. The package folder also holds a
  Windows service, `CoworkVMService` (`app\resources\cowork-svc.exe`; automatic start, `LocalSystem`, started at boot
  in Windows session 0, owning no window in the user's session), which outlives every close of the app and is not one
  of its processes; the app's own processes run in the user's session.
- **The desktop app's own log**, `%LOCALAPPDATA%\Claude\Logs\main.log`, read by the sync alone, before a desktop mode
  closes the app and after one starts it again; measured on the development machine over its logs of 2026-09-29 to
  2026-10-25, Claude desktop 2.9939.4 and 2.42304.0. It is a text the app does not document, which it rotates by
  renaming it to `main1.log` … `main4.log` at about 10 MB and starting a new one. Every start writes `Starting app {`
  and, 1 to 13 seconds later, `claude.ai account active and logged in`, signed in or not. The restore of a login
  stored before a sign-out in the app (2026-10-25) was refused: in the same second as that line the app wrote
  `Navigated to /logout, synthesizing logged-out`, `User logged out during IPC wait` and `User is logged out`. A start
  of an app left signed out by a sign-out in it reported `sign_in_cookie_present: false` in its start-up state and
  wrote the last two of those lines within a second or two; a sign-out in the app writes the first. No start that
  stayed signed in wrote any of the three from its `Starting app {` to eight seconds after its start line. The logins
  stored at a switch away that day were taken when put back; that the sign-out ends the web session of the login it
  leaves is measured under *The desktop app signed out*, below.
- **The desktop app signed out**, measured on the development machine, 2026-10-26, Claude desktop 2.42304.0: an account
  signed out of in the app, the app then quit from its own menu, started signed out and signed in to another account,
  `config.json` read only as its keys, the kind of each value and whether a value changed between looks. Every
  top-level key stays through the sign-out and the quit, and both login values stay non-empty strings:
  `lastKnownAccountUuid` keeps naming the account signed out (the sync's watch record went on naming it, and the next
  sign-in logged its transition from that account), while `oauth:tokenCacheV2` and the older `oauth:tokenCache` are
  rewritten smaller (the file shrank at the sign-out, and again at the quit by keys that do not bear on sign-in). The
  one other key the sign-out changed, the boolean `windowSizeWasSignedIn`, held one value in every signed-in look of
  the measurement and the other in every signed-out one, a start whose login was refused included.
  `Network\Cookies` kept its size throughout, an SQLite file whose size does not show the sign-in cookie going;
  the sign-out did not write it at once, the quit did, and the next start reported `sign_in_cookie_present: false` and
  `signed_in_at_last_exit: false`, then `User logged out during IPC wait` and `User is logged out` within a second. The
  sign-out also recreated the app's claude.ai IndexedDB store and wrote its Local Storage. Which value is which was read
  the same day, Claude desktop 2.42304.0, from the `config.json` of the app signed in, that one boolean alone:
  `windowSizeWasSignedIn` occurs once in the file and is `true`. True is therefore signed in and false signed out, and
  the sync reads it as the app's sign-in mark (*Rules*). The measurement also isolated the sign-out's effect on a stored
  login: a login stored the day before was taken at a switch, the account was signed out of in the app, and the same
  stored login was refused at the next switch back, the app writing `Navigated to /logout, synthesizing logged-out`
  and the other two signed-out lines in the second of its start line, with `sign_in_cookie_present: true` in its
  start-up state. The sync's check confirmed the two switches that stayed signed in eight seconds after the start line
  and found the refusal in the same second.
  A close by the sync begins the app's quit but not its cleanup: the app logs `Windows session ending (shutdown) -
  quitting the app`, and neither its `beforeQuit` handler nor any `onQuitCleanup` handler (among them the flush of its
  web storage, `flush-web-storage`) is logged after it, where a quit from the app's menu runs them all; the next start's
  `[quit-cleanup] previous quit` block says `completed: false` with no `cleanup_ms`, or is absent, and its start-up
  state's `previous_quit_clean` is false or null, where a quit from the menu leaves both true. A login stored at such a
  close holds what the Cookies file held when the app ended, which can lack a sign-in made just before (*A sign-in
  reaching the Cookies file*, below).
- **A sign-in reaching the Cookies file**, measured on the development machine, 2026-10-26, Claude desktop 2.42304.0,
  from file times, the system volume's change journal (`fsutil usn readjournal`, filtered to the app's `Network`
  folder) and the app's log, no login value read. The app writes `Network\Cookies` in batches, not at each change:
  after each of two starts its first write to the file came 30 seconds later. It holds the file open while it runs,
  so the journal records no later write until the file is closed, while the file's last-write time goes on moving. A
  sign-in at the app's sign-in page writes a line stamped, like every line, with the app's local time to the second,
  holding `Login-state transition (loggedOut: true → false, uuid: <left> → <new>)`. The rest of a sign-in is prompt: at
  one sign-in the app logged `sessionKey names a different account than the flow` a second before that line, and the
  sync's watcher recorded the new account from `config.json` four seconds after it; only the Cookies file lags. A login
  stored too soon lacks its sign-in cookie: after one sign-in the sync's close came 15 seconds later, and the login it
  stored, put back hours later, was refused — the start-up state said `sign_in_cookie_present: false` and
  `signed_in_at_last_exit: true`, a second before `User logged out during IPC wait` and `User is logged out`, with no
  `Navigated to /logout`. A login stored before a sign-out in the app is refused otherwise: its start said
  `sign_in_cookie_present: true`, a second before `Navigated to /logout, synthesizing logged-out`. The flag in the
  start-up state therefore tells the two refusals apart.
- **The desktop app's changes of sign-in**, measured on the development machine over its logs of 2026-10-25 to
  2026-11-01, Claude desktop 2.42304.0: every change of the app's sign-in writes a line `Login-state transition
  (loggedOut: <old> → <new>, uuid: <left> → <reached>)`, naming the sign-in mark's old and new value and the account it
  leaves and the one it reaches. Each of four sign-outs in the app wrote `loggedOut: false → true, uuid: <account> →
  <none>`, each ending that account's web session; no start wrote one, neither a start that refused the login it was
  given nor a start at the sign-in page for an add. Each sign-in at the sign-in page writes `loggedOut: true → false,
  uuid: <left> → <account>`, and makes a web session of its own. A login
  stored at a close holds the session the app then held, so the first of these lines after the store that names its
  account tells whether that session has ended (*Rules*, *A stored login whose web session has ended*).

## Contracts

| Contract | Producer → consumer | Canonical statement |
|---|---|---|
| `events.jsonl`, `watch.json` | sync → ledger | `sync/WindowTallySync.ps1` (description), `windowtally/ingest_sync.py` |
| readings v1 | plugin → ledger | `windowtally/ingest_readings.py` |
| browser readings v1, the message and the file | browser extension → its host → ledger | `windowtally/browser_host.py`; the extension's side `extension/background.js` |
| `sync-settings.json`, the stored desktop logins | the sync → ledger, window | `sync/WindowTallySync.ps1` (description), `windowtally/sync_store.py` |
| the sync's modes, exit codes and the notes the window reads | window → the sync, as a process | `sync/WindowTallySync.ps1` (description), `windowtally_gui/sync_model.py` |
| `status.json` v3 | ledger → plugin, window | `windowtally/status_file.py` |
| `bills.json` v1 | the user, `bills add` or the window → ledger | `windowtally/bills.py` |
| `settings.json` v1 | the user, `bills source`, `bills remind` or the window → ledger, window | `windowtally/settings.py` |
| a bill archive's manifest | the user's archive → ledger | `windowtally/bills_manifest.py` (the columns read) |
| `window.request` | a second start of the window, the plugin's window button → window | `windowtally_gui/instance_model.py`; the plugin's side `plugin/hooks/window.ts` |

A version change in any of them is made on both sides together; a consumer refuses a version it does not know
and says so, it never guesses. The plugin's side of readings v1
and status.json is `plugin/hooks/readings.ts`, `plugin/hooks/status.ts` and the shapes in `plugin/types/index.d.ts`;
of `window.request`, the file the table names. The window reads status.json through
`windowtally_gui/status_model.py`, and writes bills and settings only through `windowtally.bills` and
`windowtally.settings`, so it writes no shape of its own into them. A manifest carries no version: it is read by
its columns' names, and one missing a column read is refused whole. A file the user writes is refused whole when any
part of it breaks its contract, every problem named — save, since 2026-11-04, a bill source's bills: a source whose
document breaks its contract is refused whole as before, but within one a bill that breaks it is left out alone and
named, the source's other bills counted, and the accounts it may concern are said not to be wholly read (*Rules*,
*Bill sources* and *What was not read*). `settings.json` keeps the whole-file rule, and every writer of a bills file
refuses one it cannot read whole. A key added without a change of version is read as false by every
reader where it is absent: status.json's `notificationsSilenced` and `recommended.reliefExact`, and settings.json's
`silenceNotifications`, all added on 2026-10-22 (*Decisions*). Added on 2026-10-25 without a change of version, each
read as the contract says of an absent key: status.json's `syncFollows` (written only as false; absent, the CLI
follows), `oneClickDesktop` (written only as true; absent, unavailable), `workingSessions` (written above zero; absent,
none) and an account's `desktopArchived` (written only as true; absent, no stored login). The sync's exit codes grew
on 2026-10-25 by 5, a switch of the desktop app that came up signed out, which the window reads as not done, in the
script's words; and its store by `desktop-login.refused.dpapi`, a stored login the app refused, which no reader counts
as a stored login. Since 2026-11-01 that file also holds a stored login whose web session the watcher found ended
(*Rules*), with no change for any reader. The sync's modes grew on 2026-10-26 by `AddDesktop`, which stores the
login the app holds and leaves the app at its sign-in page, ending 0, 1 (an app that came up signed in all the same
among its errors) or 2, with no exit code of its own; the window runs it for *Add an account* and shows a pass in
the script's last note, anything but 0 as not done. Every desktop mode that stores or puts back a login —
`SwitchDesktop`, `SnapshotDesktop` and
`AddDesktop` — reads the sign-in mark, `config.json`'s boolean `windowSizeWasSignedIn`, and refuses (2) a file where
it is absent, repeated or not a boolean; `SwitchDesktop` and `SnapshotDesktop` act differently on an
app at its sign-in page (*Rules*), their codes unchanged. Added on 2026-10-26 without a change of version: `watch.json`'s
and status.json's `desktopSignedIn`, written only as false, while the desktop app is at its sign-in page — its
`desktopAccount` then null, and in status.json no account `isDesktop` — and absent where the app is signed in or its
sign-in is not known; and `events.jsonl`'s kind `desktop_signed_out`, the app left at its sign-in page, whose account
is the one the app's storage still names, the one signed out of, and from which the ledger's desktop timeline names no
account (*Rules*). The notes the window reads from the sync, beside its exit code, grew on 2026-10-26 by a third
marker: `Waiting for the desktop app to save its sign-in`, written while a desktop mode waits, before it closes the app,
for a sign-in just made to reach the Cookies file, during which the run can still be called off; `Closing the desktop
app` and `Starting the desktop app` are as they were. The window is the only reader of these markers; a window older
than the script shows its own progress words through the wait. The modes, the exit codes and every file the sync
publishes are unchanged by it: exit 5 keeps its meaning whichever refusal its note names. Added on 2026-10-26 without a
change of version: settings.json's `accountOrder` and `accountNames`, each written only where it says something — an
order other than the order by name, a name — and read as the order by name and no name where absent. status.json gains
no key: its `accounts` now stand in the order every surface keeps, and an account's `label` is its name as shown, the
user's own where one is set (*Rules*, *One order, one name*). Changed on 2026-10-26 by the maintainer's decisions on the
sync's robustness (*Decisions*), with no exit code added: exit 2 of the modes the window runs is a refusal with no
login changed, its note saying so
where the app had been told the session ends and may be partly closed, and saying nothing was changed only where no
close had begun; exit 3 is also a `SwitchCli` to the account the CLI has signed out of, whose stored sign-in is then
not put back, which the window answers as it answers an account with no stored CLI sign-in, with a terminal for
`claude auth login`. `SwitchDesktop` starts the app whether or not it was running, so `Starting the desktop app`
follows every switch that puts a login back. `Snapshot` gains `-SignedIn`, which the launcher passes after a `claude
auth login` that ended 0; the script gains `-SignInWindowSeconds` (30), and `-CloseSeconds` defaults to 120.
`watch.json`'s `condition`, and with it status.json's `cliCondition`, keeps its meaning — what keeps the CLI from
following the app — and gains a text within it, a CLI signed out of the desktop app's account, while its refusal of a
label another program wrote now stands only where the sign-in file was rewritten since that label appeared, so that
whose sign-in it holds is not known (*Rules*, *The CLI's sign-in*). The script's own `state.json`, which no other part
reads, gains the keys `restoredStamp`, `lookedAt` and `seen`. The script gained `-CookieSaveSeconds` on 2026-10-27
(35, its least, so it can lengthen the wait for a sign-in to be saved but never shorten it), which no caller passes and
the tests use to hold a sign-in in the wait however slow the machine; the sync's behaviour is unchanged by it. Added
on 2026-10-27 without a change of version: `watch.json`'s and status.json's `desktopRunning`, written only as false,
while none of the desktop app's processes runs — its `desktopAccount`, and in status.json the account `isDesktop`,
still naming the account the app starts on, and `desktopSignedIn` whether it starts at its sign-in page — and absent
where the app runs or whether it runs is not known (*Rules*, *The desktop app not running*). The watcher writes its
view whenever it changes and, while the app is not running, at every look, so that the view's `t` stays newer than any
event written before that look; a look that finds the act mutex held by another of the sync's acts writes nothing.
status.json carries the key only from a view at least as new as the desktop timeline's last point and no older than
two minutes (`service.NOT_RUNNING_FRESH`). The sync's modes grew on 2026-10-27 by `StartDesktop`, which the window
runs to start the app: it ends 0 when it started the app or found it running and started nothing, 2 when another of
the sync's acts holds the act mutex past its wait, and 1 on an error, with no exit code of its own; a start writes
`desktop_account` naming the account the app's storage names, or `desktop_signed_out` naming it where the app starts
at its sign-in page, as a switch records it, and storage it cannot read writes no event. Its notes are `Starting the
desktop app...` and `Started the desktop app.`, or `The desktop app is already running; nothing was started.`; the
window shows the last of them. `-DesktopLauncher` is required beside a `-DesktopAppDir` of its own for `StartDesktop`,
as `-DesktopAppDir` already was beside a `-DesktopConfig` of its own, so that a simulated desktop never starts the real
app. Changed on 2026-10-31 without a change of version, as Anthropic renamed Max 20x Ultra (*Decisions*): the plan's
key `max20x` is `ultra` in bills.json's `plan` and in status.json's `plan` and `profilePlan`, and its name in
`planName` is Ultra; a manifest's line item `Max plan - 20x` reads as `ultra`. A bills file holding the former key was
refused whole, the plan named; since 2026-11-04 the bill holding it is left out, the plan named. Added on 2026-10-31
without a change of version, as Anthropic began removing the
5-hour limit account by account (*Decisions*): status.json's `fiveHour.state` value `no_limit`, the account having
no 5-hour limit (*Rules*, Windows), its `percent`, `resetsAt` and `exhaustsAt` null, its `asOf` the latest reading on
which the limit stands removed, `estimated` and `anchorExact` false. The `fiveHour` object stays, since the plugin's
reader refuses a status without it; a reader that does not know the state shows the window as unknown. Added on
2026-10-31 without a change of version, by the maintainer's decisions on accounts no longer used (*Decisions*):
settings.json's
`hiddenAccounts`, the accounts the user hid, by UUID, each once, written only where it lists one and read as none
hidden where absent; and an account's `hidden` in status.json, written only as true, on an account the user hid that
neither the desktop app nor the CLI uses, and absent where the account is listed (*Rules*, *Hidden accounts*). A
reader that does not know the key lists the account, as before. With every account hidden or its plan ended,
status.json's `recommended` names no account and no relief moment, as with no account known, its reason saying that
none is left to recommend (*Rules*, *Recommendation*). Added on 2026-11-02 without a change of version, by the
maintainer's decision on claude.ai's use by product (*Decisions*): the browser reading's `weeklyByProduct`, in the
message and the file — `asOf`, `windowStartedAt` and `rows` of `key`, `name` and `percent` — which the extension sends
only where claude.ai's response carried it and the host checks on its own, after the rest of the message: one it
cannot take is left out of the file, the windows written, and its answer is `{"ok": true, "dropped": "<why>"}`, which
the service worker logs to Chrome's console; and status.json's `byProduct` on the weekly window — `asOf` and `rows`
of the same three — written only while the account's latest report is of the weekly window in effect (*Rules*, *Use
by product*). A host that does not know the key builds its file without it, a reader that does not know it shows the
window as before, and a `byProduct` not in its shape is read as absent by the window and the plugin alike, never as a
fault of the file; no figure of either file rests on it. Changed on 2026-11-03 without a change of version, as
invoices since the renaming print the plan's line as `Claude Ultra` (*Decisions*): a manifest's line item
`Claude Ultra` reads as `ultra` beside `Max plan - 20x`, both whatever a bill's date; before, it was a line no table
named, and a manifest holding it was refused whole. Changed on 2026-11-04 without a change of version, by the
maintainer's decisions on accounts whose plan has ended (*Decisions*): status.json's `accounts` stand with the accounts
whose `subscription` state is `ended` after all the others, in the user's order among themselves, an account in use
first whatever its plan (*Rules*, *One order, one name*); no key is added, and a reader keeping the order shows them
last. Added on 2026-11-04 without a change of version, by the maintainer's decisions on refunds and on bills not read
(*Decisions*): bills.json's kind `refund` — `account`, `date` (the day the refund was issued), `amount` (the sum
returned, unsigned), `currency` (the credited bill's) and `reference`, required, naming the credited bill by that
bill's reference, with an optional `note` and no `plan`, `start` or `end` — which a WindowTally that does not know the
kind refuses by naming it; a manifest's document types `CreditNote`, read as an invoice row is, and `Refund`, not
read, as a receipt is not; status.json's subscription state `unread`, the account's bills not all read, its `plan`,
`planName`, `paidUntil`, `daysLeft` and `thisMonthListPrice` null, `renewSoon` false and `profileCheck` `unread`; and
status.json's top-level `billsUnread`, written only as true while some bill a source holds may not have been read,
`thisMonth.plansAtListPrice` then null, absent meaning every bill was read. A reader that requires the month's sum as
a number refuses the whole document rather than state an absence; the window and the plugin take a null sum only
with the state `unread`. Added on 2026-11-10 without a change of version, by the maintainer's decisions on Fable's
weekly window (*Decisions*): the browser reading's `weeklyScoped`, in the message and the file — a list of rows of
`name`, `percentUsed`, `resetsAt` and `allowanceOfWeekly`, the last null where claude.ai gave none — which the
extension sends only where claude.ai's response carried a per-model window and the host checks on its own, as it
checks `weeklyByProduct`: one it cannot take is left out of the file, the windows written, and where both are left
out the answer's `dropped` gives both reasons; and status.json's `scoped` on the weekly window — rows of `name`,
`state` (`current` or `unknown`), `percent` (null while `unknown`), `resetsAt`, `asOf`, `estimated` and
`allowanceOfWeekly` — written only for an account that has used the model (*Rules*, *Per-model windows*). A host that
does not know the key builds its file without it, a reader that does not know it shows the weekly window as before,
and a `scoped` not in its shape is read as absent by the window and the plugin alike; the weekly window's
`exhaustsAt` allows for it, and no other figure of either file rests on it. Added on 2026-11-11 without a change of
version, by the maintainer's decisions on keeping the computer awake (*Decisions*): settings.json's `keepAwakeOff`,
written only as true, the user having turned the service's keep-awake off, and read as on where absent; any value but
true or false refuses the file. status.json gains no key: `workingSessions` keeps its meaning, the desktop-hosted
sessions with a turn in progress, now counted off Claude Code's session registry (*Sources*), and a registry file the
reader does not recognise is one of `sourceErrors`. Added on 2026-11-11 without a change of version,
by the maintainer's decisions on resets outside the schedule (*Decisions*): status.json's `thisMonth.inPlans`, the
part of `apiEquivalent` the plans covered, and `thisMonth.withinOneWindow`, the part of that within one full weekly
window a week, each written only where it is less, in cents, than the sum before it, so that an absent key means the
same sum (*Rules*, *What the plans covered*). A reader that does not know them sets the plans' cost against
`apiEquivalent`, as before; the window and the `status` command read both, the plugin neither.

## Rules

- **Windows.** A 5-hour window starts with the first message after the previous one ended and lasts five hours;
  past its end it is not started until the next message. The weekly window resets at one instant every week.
  Usage only raises a percentage; a fall of three points or more is a reset (`limits`). An account may have no 5-hour
  limit, Anthropic removing it account by account, after which the server sends that account's weekly window alone
  and every source leaves the 5-hour window out of its readings. The limit counts as removed once the account's
  readings since its last 5-hour figure carry the weekly window alone, at least two of them and `limits.NO_LIMIT_SPAN`
  (15 minutes) apart, and holds again from the next reading that carries a 5-hour figure
  (`limits.five_hour_removed`): Claude Code hands on one such reading for a moment where a 5-hour window has just
  ended. Such an account is judged by its weekly window alone — the recommendation, the warnings and every surface —
  and nothing is inferred for its 5-hour window from its responses.
- **A window's figure** is the highest any observation of the window now running has read, never merely the latest:
  Claude Code sessions running at once each hand on the reading their own latest response carried, so one can trail
  another's, and the desktop app rounds the figure a point higher than Claude Code a third of the time in the 5-hour
  window and half the time in the weekly one, so a lower figure read after a higher one says less. An observation
  counts for the window when it was taken a minute or more after the window began (`limits.WINDOW_START_MARGIN`) and,
  where it carries a reset time, names the window's end (within `limits.SAME_WINDOW_END` in the 5-hour window, half a
  week in the weekly one); in the weekly window only those since its last fall of three points or more count, such a
  fall being a reset no schedule showed, and where no weekly reset time is known, from a reading or the account's
  anchor, the latest observation stands alone. The latest observation is always among them, and the standing is as of
  its time. The projection of when a window fills runs on the same observations, each counted at the highest figure
  read up to it (`limits.five_hour_standing`, `limits.weekly_standing`, `limits.exhausts_at`).
- **Idle accounts are never polled.** An idle account's figures stand until its next reset, so its standing is
  its last observation rolled forward through the reset times, shown with the observation's age.
- **Reset times.** A plugin reading or a browser reading carries the exact time. Without one, the weekly instant is inferred from the
  app samples' falls (the phase of the week scoring best on the falls it explains less twice the steady
  stretches it contradicts, the middle of the best run), and a fall the schedule does not explain is a reset outside
  it, whose kind the history reads (*What the plans covered*).
- **Estimates.** Between observations, a rise is estimated from the API-equivalent cost of the account's responses
  since the latest observation, or since the window began where it began after it, and added to the window's figure,
  at the points-per-dollar rate of the last two weeks: the points over the dollars of the steps whose later
  reading falls in them, the steps *What a full window holds* sets out (below) without its test of the plan, once
  their dollars reach $5 (`limits.percent_per_dollar`). Every inferred figure is flagged and shown with ≈.
- **Attribution.** A request runs on the account its client is signed in to at that moment: a response with a CLI
  entry point takes the CLI timeline (sync events and log), every other response — and a CLI one before the first
  CLI event — the desktop timeline (sync events and app samples); a desktop session's owner line only where no
  timeline has a point yet, the last one recorded where it names several. While the desktop app is at its sign-in
  page — from a `desktop_signed_out` event to the timeline's next point — the desktop timeline names no account, and a
  response there takes its session's owner line, else no account. A limit stop, a turn a plan limit refused, is a
  request refused, so it takes what a response of its session would take at that moment, and is derived again with
  the responses. A reading takes what a response of its
  session would take at that moment, then its weekly reset checks the answer: a reset on exactly one account's
  weekly schedule, and not on the answer's, makes the reading that account's, an account's schedule being the weekly
  reset most of the readings answered for it carry. Every assignment is derived again when its evidence changes, and
  all of them when the rule changes (`attribution`).
- **Recommendation.** Of the accounts below 95 % weekly and not running at 90 % or more in their 5-hour window, the one
  whose weekly window resets first: its remaining allowance expires first, so spending it first wastes least. With
  none below those ceilings every account is at or near its limit: of the accounts not blocked, below 99 % in both
  windows, the one with the most of its week left, an account with no weekly figure last and equal weeks to the earlier
  reset, with when room returns, the first moment an account is below the ceilings again. Only with every account
  blocked is none recommended; every account is then at its limit, with when the first opens. An account the user hid
  (*Hidden accounts*), in use or not, and one whose bills record a plan that has ended and none since — a recorded
  period, none covering today and none to come — are not weighed at all, neither recommended nor waited on: such an
  account takes no readings, so its weekly window, rolled forward through its resets with nothing read, would stand at
  nothing, or at no figure after six weeks, and read as room left. An account no bill names, one whose next period is
  still to come, one whose bills could not all be read (*What was not read*), and every account while no bill source
  exists are weighed. With every account so left out none is
  recommended and nothing is waited on, the reason saying that no account is left to recommend, which no surface reads
  as every account at its limit (`service`, `limits.recommend`).
- **Blocked time.** Hours in which every account was at 99 % or more in either window, counted only inside the
  covered period; an account not yet seen counts as unavailable.
- **No known account.** A response with no account, or with an account WindowTally does not list — one the desktop app
  signed in to before the sync stored its profile — has no known account: every chart and table puts its use there,
  in grey, and the Coverage section counts the same responses (`history`).
- **Cost.** API list prices, November 2026 (`pricing`): a yardstick, not a bill; reproduces Claude Code's own cost
  record for claude-opus-5-5 to the cent. A response of a model the price table does not name has no cost, never a
  cost of nought; every pass prices each such response from its stored tokens once the table names its model
  (`ingest_transcripts.reprice`, the pass's phase `prices`), and names each model still without a price among the
  source problems, with how many responses it has (`service.unpriced_problems`).
- **Plan periods.** A subscription bill's service period is [start, end) in UTC days, its plan in effect from its
  start until its end or until a later bill's period starts inside it: a mid-period change of plan takes effect at
  once and restarts the period, and one starting the same day as the order it replaces leaves that order no day in
  effect. A refund ends the plan of the bill it credits on the refund's date, half-open: a period of 7 May to 7 June
  refunded on 19 May held its plan from 7 May to 19 May, and one refunded on or before its start held it no day; its
  end, for every rule below, is then the refund's date. A period starting inside the one in effect is a change of plan
  when it raises the plan; one that does not still takes effect, and is reported as a source problem. A period
  starting on or after the end of every period before it is a new order — a renewal, or an order after a gap, at any
  plan: a lower plan ordered once a period has ended is never a downgrade, and an order after a refund, inside the
  refunded period's printed days, is a new order too. The days with a plan, how far an account is paid up and whether
  its plan has ended are read from each period's days in effect, so a plan a change replaced does not come back when
  the plan that replaced it is refunded (`billing`).
- **Subscription cost.** A subscription's cost is its plans' cost at their US list price, in US dollars
  (`pricing.PLAN_PRICES`), never what a bill was charged: a period of one calendar month takes the monthly price, a
  Pro period of one calendar year the yearly one, and a period of any other length is priced by the day at the
  monthly price, twelve months to 365 days, and named as a problem of the bills. A period's price is spread evenly over
  its printed days and counted on its days in effect, each day in its own UTC month, so a period cut short by a
  change of plan or a refund counts only the days before it: a Max 5x month of 7 May to 7 June refunded on 19 May
  counts $100 × 12/31. A top-up or a settlement of extra usage has no list price
  and counts in no figure. This month's figure is the whole UTC month's. Cost per day divides a month's cost by its
  days with a plan, which across accounts count each day once. Sums are exact fractions, each figure rounded half up
  to the cent on its own and every total taken from the exact values (`billing`). A bill keeps the amount and
  currency it was charged in, written after the currency's code wherever bills are listed, and so does the sum a
  refund returned, listed beside the bill it credits and entering no figure; nothing is converted.
- **Standing.** While a recorded period covers today, the account is paid up to the end of the periods that run on
  from today without a break; once none does, it has no recorded plan today, which is never called a lapse — a bill
  not yet recorded looks the same. An account whose last plan was refunded stands ended from the refund's date: it is
  paid up to no later day, no renewal is suggested, and a profile naming a plan is one no bill covers today; where no
  period of it held a day, each refunded on or before its start, its plan ended on the day of the last refund. The
  renewal reminder, off by default, tags an account within its days of that end. The profile's plan
  (`organizationType` `claude_pro`, or `claude_max` with the tier `default_claude_max_5x` for
  Max 5x or `default_claude_max_20x` for Ultra) is set against the plan in effect today; a difference from a profile
  fetched before the period began is the profile being older, not a difference.
- **A bill's account** is every account WindowTally knows with the bill's e-mail, compared case-insensitively, the
  one whose profile is on this machine standing for them; the bills of an e-mail no account here has are counted under
  it.
- **A period's API-equivalent use** is the list-price cost of the responses the ledger attributes to the account
  while the period was in effect, up to now, set beside the period's cost at list price. It is marked when the
  ledger's record of the account begins inside the period, and absent when the ledger has none from then. On the
  history's surfaces it is split by what the plans covered (*What the plans covered*): the part paid outside the
  plans is said beside the sum where it reaches half a dollar, and the use the plans covered is given as a multiple
  of the period's list price, with resets and, where the two read differently in whole numbers, without them
  (`history._period_use`).
- **What a full window holds** (`capacity`). One full 5-hour or weekly window — 100 % of it — held 100 × the dollars
  over the points, summed over steps (`limits.rises`), the steps the estimates' rate is counted from. A step is two
  consecutive readings of one account's window from one instrument inside one run, the points the later reading took
  the run's highest reading so far up by, never negative, and the list-price cost of the account's responses after
  the first and up to the second, which may be none, a response paid outside the plans (*What the plans covered*)
  counting nothing: it raised no window of the plan, and counted it would make a window seem to hold more than it did
  (`capacity.steps`). An account's plugin readings of a window are its instrument
  from the first of them on, its app samples before that, and a step never pairs the two; the browser extension's
  readings are never one, though they read the same figure: the two instruments divide an account's time between
  them, so a run of browser readings would measure spending one of them measures already and count it twice. A
  run is consecutive readings of one instrument inside one window; it ends between two readings more than three hours
  apart (`limits.CALIBRATION_MAX_GAP`), either at 99 % or more, with a fall of three points or more between them — save
  in the 5-hour window between readings naming one window end (`limits.SAME_WINDOW_END`), which only that end resets —
  a reset between them by the readings' reset times, else by the 5-hour window rule or the account's weekly anchor,
  or a response between them with no list price, and here also where the bills do not put the account on one plan at
  both. Claude Code sessions running at once each hand on the reading their own latest response carried, so one
  session's reading can trail another's taken seconds earlier by a few points: inside a run such a reading adds
  nothing, nor does the rise back from it, the run rising by its highest reading less its first. A run across which
  nothing was spent here is left out whole. An account's plan
  is the recorded plan in effect, a plan's periods that run on into each other joined, the UTC day a plan began or
  changed being no plan's, a refund's date ending a plan as its printed end does; an account with no bills, or whose
  bills could not all be read (*What was not read*), is not measured. A plan's accounts count together. Readings are
  whole points, so a figure is stated only where the rise is at least ten points per square root of the runs of
  consecutive steps it sums, the rounding then moving it by a tenth or less, and otherwise reads —; two figures differ
  only by more than the sum of what the rounding can move each. Per plan the figure is over the range, every plan of
  the bills' vocabulary given a row with the accounts the bills put on it in the range; week by week it is per plan
  per local week from Monday, a step in the week of its later reading, and a week marked higher or lower where its
  figure reads differently from the plan's last stated one and differs from it. Per plan and per week, beside the two
  figures, stands how many full 5-hour windows the full weekly window held: the weekly figure over the 5-hour one, to
  a tenth, with the range the two figures' rounding leaves it in, their spreads as shares of themselves added; it
  reads — where either figure does or holds no dollars. A week holds 33.6 five-hour windows back to back
  (`limits.WEEK` over `limits.FIVE_HOURS`), so a quotient below that says the weekly limit, not the 5-hour one,
  decides how much a week allows (`history._windows_text`). A sum is in whole dollars from $10, in cents below. The
  history page counts six weeks, the History window its span.
- **Use by product** (`products`). claude.ai's split of an account's weekly window by product reaches WindowTally only
  through the browser extension, as a report: when claude.ai computed it, the start of the weekly window it covers,
  and each product's key, name and whole-percent share of the window's use up to then, in claude.ai's order. The
  ledger keeps each report once per organization and moment computed (`product_shares`, one row per product), beside
  the weekly figure of the reading that brought it; a report received again stands as the first reading that carried
  it, a product a later reading of the same moment adds coming after its rows. The shares are cumulative over the
  window, so a window's last report stands for it, and two reports are of one window when their starts lie within an
  hour of each other (`products.SAME_WINDOW`), claude.ai's start for one window moving by under a second between
  responses (*Sources*). An account's current report is its latest one, provided its window has not ended and, where
  the account's weekly reset time was read rather than inferred, that reset time ends its window, within the same
  hour; an inferred reset time can be hours off and is not compared. status.json carries the current report on the
  weekly window. The plugin's panel and the window's cards end the weekly window's words with the products above zero,
  in claude.ai's order, and the report's age (`by product 3h ago: Claude Code 82%, Chats 18%`), where at least two
  products took a share — one product alone says nothing the figure does not — the history page's account cards the
  same, wherever a product took one, with the report's time; the band and the tray's tooltip show none. Under the
  weekly chart, the history page over its six weeks and the History window over its span table each account's weekly
  windows by their last report computed in the range: the account, when the window began, the weekly figure the
  report came with, a column per product — the latest report's products in its order, then any only an older report
  named — reading — where a report named no such product, and when claude.ai computed it; with no report in the range
  nothing is shown.
  A cell gives the product's share and, beside a share above zero, the points of the weekly limit it stands for, the
  share of that weekly figure (`history.share_text`): `15% · 8 pts`, to the whole point, a share in whole percents
  being half a percent either way, and `<1 pt` below half a point; a share of zero, or one whose report came with no
  weekly figure, stands alone.
  Which products there are is claude.ai's, so one it adds is carried and shown under its own name. No figure, warning,
  recommendation or measure rests on the shares, and without a report every surface reads as before.
- **Per-model windows** (`limits.scoped_standings`). A model may have an allowance of its own inside the weekly
  window, as Fable has: claude.ai reports it beside the weekly window, with the allowance as a share of the week, and
  only the browser extension reads it (*Sources*). The model's use counts in both, its part of the weekly window being
  its own percentage times that share; past its allowance the model goes on at usage credits, outside the plan, and
  its use raises the weekly window no further; and a reset of the allowance, which the user can take, gives its part
  of the week back, the weekly reset unchanged. The ledger keeps each reading (`scoped_windows`), attributed by
  organization as the browser's other rows are. A model's window is shown only where some reading of it in the last
  six weeks stood above nothing. Its standing is its latest reading carried forward and flagged ≈. The weekly window's
  rise between the first weekly reading since and the latest is shared between the model and every other model in
  proportion to what each spent between those two readings at its own points per dollar — the API-equivalent cost of
  the model family's responses (Fable's family counting Mythos, `pricing.model_family`, the window's name mapped to
  its family by the family's words, `pricing.family_named`) and of every other response — and the model's part, over
  the allowance, is added, the allowance capping it; what the model spent outside those two readings is added at its
  points per dollar alone. Every other family's points per dollar is measured from the estimates' steps of the last
  two weeks (*Estimates*, above), a run of steps at a time: a run whose dollars are at most 1 % the model family's
  measures every other family, its points over their dollars, once those reach $5. The model family's is read off
  claude.ai's readings of the model's own window wherever they measure it (`limits.read_rate_of`). Each reading of
  the last two weeks is measured from the reading before it in the same week: the points the window rose between the
  two, times the allowance's share of the week, over what the family's responses between them cost. A week's first
  reading is measured from the week's start, where the window stood empty, once the window was read in an earlier
  week and the weekly window was observed by that start, which together show the account's use was recorded from the
  start on; otherwise it only sets the level the next is measured from. A reading with no reset time, or within a
  minute of its week's start, where it may still show the week before, is passed over. Two readings measure nothing
  where no reading has yet given the allowance; where either stands at 99 % or more; where the window fell three
  points or more between them, or the weekly window fell while they ran, the reset having come between the weekly
  observation that showed the fall and the one before it; where a response of the family between them has no list
  price; or where the family spent nothing here between them, its use then being elsewhere. Short of a fall the next
  reading is measured from the higher of the two, and no bound is set on the time between two readings, which come
  only while claude.ai is open. The rate is the points over the dollars once the dollars reach $5. Without it the
  model family's rate is what the steps leave: every run not measuring the other families, its points less what the
  other families' dollars in it cost at their rate, over the family's dollars once those reach $5 — a remainder, which
  carries the other families' rate's error whole and leans low where the family's allowance stood full across a run
  (`limits.family_rates_of`). Where either rate is not measured the rise is shared by the dollars alone, and where the
  model family's is not, its spend outside the readings is added at the weekly window's single rate
  (`limits.family_rates`). A scheduled reset since empties the
  window, a reading with no reset time taking the week's next reset from the weekly observations; and a fall of the
  weekly window since, read by the weekly window's rule for a fall, that gives back about what the model held of the
  week — within three points, or a quarter of that part — is a reset of the allowance, which starts again from nothing
  and is flagged ≈, while any other fall the model could have been part of leaves the window unknown until claude.ai
  is read again; a fall while the model held under three points of the week is not its own, and the model's figure
  stands across it. The weekly window's projection stops the model's part of its pace — its part of the use over the
  projection's span, shared as above — once the model's allowance, as it stood at the latest weekly observation, is
  used (`limits.projection_plateaus`, `limits.exhausts_at`). status.json carries the windows on the weekly window; the
  band shows each after the weekly figure by the model's name, `Fable ≈24%`, its reset only where it is not the
  week's, and a group of its own on the desktop's line of the account in use, its figure with no meter; the panel a
  row under the weekly one, with a meter on the desktop,
  with the allowance's share of the week and the age of the claude.ai reading; the window's card a row under the rings,
  its name, its figure and a thin bar of its own, and its words on a line behind the bar's key. The recommendation, the tray icon, the tooltip, the history page and the History window show none
  of them; the history reads their readings only to tell a model's use past its allowance and a reset of it (*What the
  plans covered*).
- **What the plans covered** (`plan_use`). The history sets the API-equivalent use beside the plans' cost at list
  price, and two parts of that use would make the multiple say more than the plans gave; both are found response by
  response, from the readings alone, over every account's scheduled weeks. *Outside the plans* is use paid at extra
  usage: a response made while the account's weekly or 5-hour window stood exhausted, at 99 % or more, until the window
  reset (`limits.blocked_spans_of`), and a response of a model with an allowance of its own (*Per-model windows*) made
  while that allowance stood full, its level a claude.ai reading of it, or nothing at its week's start, carried forward
  to just before the response by the live figure's rule (`limits.ScopedCarry`) through every reset read by then — the
  weekly reading the response itself brought among them, since a fall it shows came before it. A model has an
  allowance from the moment claude.ai first read its window, on any account, and in every week after it, whether
  claude.ai was read that week or not; before that moment its use is the plans' and no fall then is its reset, and in
  the week that moment falls in the carry counts the model's use from the week's start, as that first reading itself
  does. From then on an account with no reading of the window takes the allowance as unknown, and none of its use
  counts as past it; an account's allowance for a week is the last claude.ai gave it by the week's end, else the first
  it gave after. The rates the carry takes are the live figure's as they stood at the week's end, or at the range's end
  where that comes first. *Beyond one window* is the use the plans covered after the account's week had used more
  than one full weekly window: the room a reset outside the schedule made. A week's use is counted in points, every
  reading's rise above the highest read since the week began or since its last fall of three points or more, the count
  going on from the first reading after such a fall, so the use between a reset and that reading is not counted and
  what a reset made room for is never overstated; the dollars between the two readings across which the count
  passes 100 are split by the points on either side, and every later response of the week is beyond. A week with no
  such fall never passes 100. A week ends at its readings' own reset time, else at the account's weekly anchor, and a
  reading within a minute of its week's start, naming a window already over, or naming one half a week or more before
  the latest read is left out, as the live figure leaves it out. Every fall of three points or more inside a week is a
  reset outside the schedule, of one of three kinds: a model's allowance, where it gave back about what the model held
  of the week, by the live figure's rule (*Per-model windows*); extra, the week given back, where the model held under
  three points of the week, the fall gave back more than the model held and the tolerance, or no model had an
  allowance of its own when it fell; and of a kind not known, where the model was used while its allowance was not
  read for the account, or the fall gave back less than the model held. Either reset is one Anthropic hands out at
  random, free and not for sale, which the user takes when they choose; the week's own reset comes at its fixed time
  and ends the week rather than falling inside it. The multiple *with resets* sets the use the plans covered — all of
  it less the part outside them — against the plans' cost, the multiple *without resets* the part of that within one
  window a week. The summary shows the part outside the plans after the cost per day where it reaches half a cent,
  `API-equivalent ÷ plans` as the multiple with resets, and `Without resets ÷ plans` after it only where the two read
  differently to a tenth; the month's line in the window's header and the `status` command says the same of this UTC
  month from status.json, `This month: $1,284 API-equivalent, $84 outside the plans · $300 plans at list price · 4.0×
  · 3.6× without resets`, each part only where it applies (`billing.month_totals_text`); a plan period's cell splits
  its use the same way (*A period's API-equivalent use*), and what a full window holds counts the plans' dollars alone.
  The weekly chart marks each reset by its kind in the account's colour, a disc for an extra reset, a diamond for a
  model's allowance and a square for a kind not known, the three of one area; its legend names each kind it shows
  once, by an outline in the quieter ink, the first saying the marks wear the account's colour, and a mark's words say
  the account, the kind, the two readings it fell between and the points it gave back. After the chart and the use by
  product, *Resets outside the schedule* tables a row per account and week with a reset read in the range — the
  history page over its six weeks, the History window and its export over the span: the account, when the week began,
  how many extra resets, a column per model whose allowance a reset gave back and one for the kind not known only where
  such a reset is counted, the points they gave back, and the week's use beyond one window, — where none; with none in
  the range it says *None.*, and its heading's hint says how each is counted (`history.reset_table`). The history splits
  the use once per computation, from the earliest of its range and every recorded plan period's start
  (`history.uses_start`); the service splits this UTC month's in the status phase of every pass, a failure there named
  among the source problems as `plan use: …` and status.json written without the two keys (*Contracts*). A reset while
  no reading was taken, or one of under three points, leaves no trace, and use at extra usage is found only where the
  readings, or the carried estimate, show a window exhausted or an allowance full. The live ≈ estimates are unchanged
  by any of it: their points per dollar still count every dollar spent (*Estimates*).
- **Bill sources.** A source whose document breaks its contract — a bills file that is not JSON, of another version,
  with an unknown key at its top or no list of bills; a manifest that is not CSV or lacks a column read — is refused
  whole, as is one that cannot be read. Within a source the unit is the bill: an entry or a row that breaks the
  contract leaves out the bill it belongs to — in a bills file every entry of its account and reference, of its
  reference alone where its account cannot be read; in a manifest every row of its invoice number — named among the
  source's problems, the source's other bills counted; one naming no reference or invoice number belongs to no bill
  and is left out alone, named. A manifest gives one bill per paid Claude invoice, from its invoice row, and that
  bill's refund from its credit note's row, which names the invoice's account, line item and printed period; a
  receipt and a refund's own document are not read, and a voided row is skipped whatever its document type. A bill is
  left out where its invoice row is missing or repeated, where it has two credit notes, or a refund's own document
  without its credit note. The same bill — one account, one reference — read twice counts once when the copies agree
  and not at all when they differ, named either way; a refund is a document of its own, never a copy of the bill it
  credits, and two refunds of one bill are two copies of one refund. Once every source is read, each refund is
  matched to the bill of its account and reference, whichever source holds either: one that matches no bill counted
  is left out, and one that contradicts its bill — another currency, more than the bill charged, a date before the
  bill's or, for a bill with a period, on or after its printed end — is left out with the bill. A refund may credit a
  bill of any kind; only a subscription's ends a plan. Writing stays strict: a bill is added, changed or removed only
  in a bills file that reads whole, and one added or changed is first set against the refund crediting it or, for a
  refund, the bill it credits, a bill and a refund left out for contradicting each other counting there so that
  either can be put right; a further source is listed only once it reads whole, the one moment the user is there to
  put it right, and is read bill by bill from then on (`bills`, `bills_manifest`).
- **Where a refund is listed.** Beside the bill it credits wherever bills are listed: `bills --list` gives it a line
  under its bill, the sum `returned on the bill [INV-0012]`; Bills and sources a row of its own directly under the
  bill, one in the bills file changed or removed there as any of its entries is; the history page and the History
  window end the plan
  period's Bill cell, and the summary's last bill, with `· refunded USD 58.06 on 2027-05-19`, the summary's count of
  bills leaving refunds out; a period refunded on or before its start reads `refunded before it began`.
- **What was not read** is never shown as what does not exist. Every account's bills are not wholly read while a
  source is refused, a listed source does not exist, the settings cannot say which sources there are, or a bill left
  out names no e-mail; an account's are not where a bill or a row of it was left out, a bill of it read twice has
  copies that differ, or a refund of it could not be matched to its bill. Such an account's subscription state is
  `unread`: no period, gap, use, plan, paid-until, renewal tag, profile comparison or cost is stated for it, its bills
  read are still listed, and every surface — the window's card, the `status` and `bills` commands, the history page,
  the History window and the plugin's panel — says its bills could not all be read and points to the source problems,
  never that it has none. It is not an account whose plan has ended: it keeps its card and its place in the order.
  While any bill is unread, this month's plans at list price across the accounts is not a known figure: the window's
  header and the `status` command say it is not known, the summary's tile reads `not known` and no multiple is given.
  On the history's surfaces a note under the subscriptions' summary says some bills could not be read, the cost table
  holds the accounts read alone, and the coverage, a gap's cover, a table of gaps holding none and a plan no account
  held are said of the bills read (`bills.Unread`, `billing`, `history`).
- **Warning figures.** A window's use is a warning from its first figure and an error from its second: the 5-hour
  window's 80 % and 95 %, the weekly window's 70 % and 90 %, a per-model window's 80 % and 95 %
  (`limits.WARNING_THRESHOLDS`, mirrored by the plugin's `alerts.ts`; the two change together). The plugin warns at
  them, and the band's figures and meters, the history page's rings and figures, the window's rings and figures and
  the tray icon's rings are coloured by them, so every surface marks one figure the same way. No reading Claude Code
  hands a session carries a per-model window, so the plugin warns of the account in use's per-model windows from
  status.json's figure, an estimate included, whenever a reading comes; such a window counts as a new one, and warns
  afresh, only on a fall of 20 points or more, since a claude.ai reading may set the estimate a few points lower.
- **One order, one name.** The accounts stand in one order on every live surface — the window's cards, its Accounts
  menu, the tray's switch menus and tooltip, the band, the folded band's card and the panel — which status.json's
  `accounts` carry and every reader keeps (`status_file.shown_order`): the account the desktop app uses, then the CLI's
  where it is another, then the rest in the user's order (settings.json's `accountOrder`), those it does not list after
  the listed ones by name — case aside, then the name itself (`accounts.name_key`), then, for accounts shown by one
  name, the UUID (`accounts.arranged`) — and a listed UUID no account has passed over, dropped at the next save of the
  arrangement; of the rest, those whose bills record a plan that has ended and none since (the subscription state
  `ended`) stand after all the others, in that same order among themselves, and a bill recorded for a new period
  returns one to its place. With no order set the rest stand by name. Wherever accounts stand by name they stand so,
  the standings — and with them the recommendation's tie-break and the history page's account cards — and *Arrange
  accounts…*'s order by name included, so that an order the user sets between two accounts shown by one name is kept.
  A switch therefore moves the cards. An account is shown by the user's name for it (`accountNames`), else by its
  e-mail's local part (`accounts.default_label`), wherever a name of it stands: status.json's `label`, and so every
  surface, the
  recommendation's reason, the history page, the History window and the `bills` command. The window's cards and the
  panel show the e-mail beside a name of the user's own, and every action names the account by its UUID. A name holds
  at most 16 characters, counted as code points, so the band, which cuts at 16 grapheme clusters, never cuts one; no
  character of the Unicode categories Cc, Cf, Cs, Zl or Zp (control and format characters, surrogates, line and
  paragraph separators — so an emoji sequence joined by U+200D is refused); no space before or after; and no two names
  in the file are the same, case aside. Settings that break any of these are refused whole, as for every key: a pass
  then names and orders nothing, and names the problem among the source problems. The history keeps the order the
  accounts were first seen
  in, which their colours follow; accounts first seen at one moment, or never, stand by the name their e-mail gives
  them, so a rename moves no colour; the history page's account cards stand by name, as the standings do. *Arrange
  accounts…*, in the Accounts menu and the tray menu, is the one place that shows the user's order itself, without the
  accounts in use first or those whose plan has ended last: Up and Down move the selected account one place, By name
  puts every account back in the default order, and a field names the selected account. A name the settings would
  refuse, one another account is already shown by, or one the settings keep for an account the window does not list —
  case aside, that account named by
  its UUID and the refusal saying that removing it from settings.json frees it — is said under the field while OK waits
  and the selection stays on that account; spaces typed around a name are dropped, and a cleared name, or one typed as
  the account's default, is no name. OK writes the order, the names and the accounts hidden (*Hidden accounts*)
  together, nothing where nothing changed, laid onto the settings as they stand then, read under the file's edit lock
  (`settings.edit_account_arrangement`, with `arrange_model.Arrangement.onto`): the order as the window shows it, as
  none while it is the order by name, so that an account added later takes its place by name, unless the window left it alone and the settings changed it
  meanwhile, when it stands as they hold it; a listed account's name as the window has it where the window changed it,
  else as the settings hold it; and the names the settings hold for accounts status.json does not list as they hold
  them — while a UUID in the order that no listed account has is dropped as above. Two orders are one where they put
  the listed accounts alike. Where the settings changed meanwhile something the window changed too, the order or a
  listed account's name, each differently, nothing is written and the window says what settings.json changed; OK again
  saves the window's over what it was told of, unless that changed once more, and Cancel keeps it. A name the window
  gives that the settings, as they stand, meanwhile gave another account — a listed one, one the window does not list,
  or a listed one whose name was cleared and whose default it now is — is refused, case aside, nothing written; a
  name cleared is never refused. Then OK runs a pass whose words follow the window's. Escape is Cancel; Return presses the button that has the focus where it is enabled, Cancel
  included, and is OK from anywhere else. The window does not open over settings it cannot read.
- **Hidden accounts.** The user hides an account by hand, in *Arrange accounts…*, and nothing hides one by itself; the
  settings keep the hidden accounts by UUID (`hiddenAccounts`), a UUID no account has kept as written. status.json
  still carries a hidden account, so a reader finds it by its UUID, and marks it `hidden` while neither the desktop
  app nor the CLI uses it (`status_file`): every live list leaves out an account so marked — the window's cards, its
  Accounts menu, the tray's switch menus and tooltip, the window's renewal notices, the band, the folded band's line
  and card, and the panel — while one a client uses carries no mark and stays listed, so the account in use is never
  left out. The window's header ends its in-use line with how many accounts are left out, and the panel's foot says
  how many and that *Arrange accounts…* shows them again. A hidden account is never recommended, in use or not
  (*Recommendation*). *Arrange accounts…* lists every account, the hidden ones included, its list's *In lists* column
  saying `shown` or `hidden` and a check box under the name field, *Shown in lists*, hiding the selected
  account or showing it again; OK writes an account's hiding as the window has it where the window changed it, else as
  the settings hold it then, and keeps hidden the accounts the settings hide that the window does not list. Having two
  values, an account's hiding is never a conflict between the window and the file. The history page, the History
  window and the `status` and `once` commands keep every account, the commands tagging one status.json marks
  `[hidden]`. Settings that cannot be read hide nothing.
- **The band.** In every Claude Code session the plugin draws every account's standing above the prompt from the last
  status.json read (`plugin/hooks/band.tsx`), the session's own account set apart: the one its use is booked to, as
  the limit warnings judge it — the desktop app's in a session the app hosts, the CLI's otherwise (`status.ts`'s
  `accountInUse`). A session the app hosts is one a window of the app draws, its `desktop` surface, or one under the
  app's entrypoint, `claude-desktop`, drawn on no terminal, which a `-p` run a desktop session's own shell starts
  inherits; a terminal's session and a `-p` run started elsewhere are the CLI's (`hosting.ts`'s `isHostedByDesktop`).
  Where it cannot be read whether the app hosts the session, the desktop band, drawn only in a
  session the app hosts, takes the app's, and the terminal's the CLI's. The other accounts follow it in the service's
  order, those status.json marks hidden left out on every band surface (*Hidden accounts*). Each
  account shows its name (*One order, one name*), one taken from its e-mail cut at 16 characters with an ellipsis, a
  character counted as a reader counts one (a grapheme cluster, so no cut splits an accent from its letter), on every
  band surface, the folded card included, and never in the panel or the window's cards, while a name the user gave it,
  at most 16 characters, is never cut; its tags `app` (`app closed` while the desktop app is not running, *The
  desktop app not running*), `CLI` and `next`; `renew 2d` in the warning colour while
  the renewal reminder finds its period ending, or `plan ended` in its place while its bills record a plan that has
  ended and none since (the subscription state `ended`), whatever else the file says — in the warning colour while a
  client uses the account, dim otherwise; and its 5-hour and weekly windows, a figure in the warning and error colours
  at its warning figures, ≈ before an inferred figure, the 5-hour window's reset as the time left (`↻1h 05m`) and the
  weekly window's as its weekday and time (`↻Sat 04:00`), its date added where it is more than six days away, so that
  it never reads as today's, and a reset marked ≈ only where no figure stands before it and its reset time was
  inferred. An account whose plan has ended and that neither the desktop app nor the CLI uses shows no figures on any
  band surface, the folded card included, only its week's reset, `week ↻Sun 21:59`, the moment a renewal is planned
  around: it takes no readings, so its figures are its last ones rolled forward through their resets to nothing, which
  would read as room left (*Recommendation*); one a client uses keeps them, its readings keeping them live. The panel
  gives such an account one dim line (*The panel*), the window a line under its cards, and the window's tray tooltip
  leaves it out; the tooltip carries no tag for one a client uses.
  In the terminal the band is one line cut at its edge, in the full words
  (`not started`, two spaces between an account's parts, `  │  ` between accounts), Details at its end; the terminal
  draws one size, so the account in use, first, is set apart by weight and colour alone, its name semibold in the
  theme's `claude` colour and the other accounts dim, and the engine folds the band there itself. On the desktop,
  unfolded, the band is two columns: the fold button `Accounts ▾`, plain and dim, over Details, plain at full
  strength; beside them the account in use on a line of its own — an orange `● `, its name semibold, its tags dim and
  smaller, any renewal or `plan ended` tag, the 5-hour figure the band's largest text, bold, with a meter and a
  semibold countdown, the
  weekly window smaller with a smaller meter and its reset, dim, any per-model window's figure with no meter, then
  the fault flags — over the other accounts, a grey
  `● ` before their compact words in smaller dim text (a dim `–` for a window not started, one space between an
  account's parts, `│ ` between accounts). With no account in use the fault flags stand on that line alone; with no
  standings, status.json's problem stands in the right column. Nothing runs past the band's width: the in-use line's
  groups and the other accounts' units wrap as wholes, and one wider than the room by itself wraps within itself. A
  meter is filled with WindowTally's status fills (`windowtally/palette.py`'s `good`, `warning` and `critical`) by the
  window's warning figures, over a grey track at 35 % opacity that shows on a light background and a dark one, the
  plugin being unable to read the app's theme; a window not started shows a dim `–` over an empty meter, and a window
  with no figure (running, unknown) its word and its countdown, and no meter. An account with no 5-hour limit
  (*Windows*) shows no 5-hour window on the band, on any of its lines, in its folded line or in the card: its weekly
  window leads, and on the in-use line takes the 5-hour window's place and scale. Folded, the band is the fold button,
  `Accounts ▸`, then the accounts the others' line shows unfolded behind a grey `● ` — or, where there are none, the
  account in use behind an orange one — in the compact words, smaller and dim, on one line in the room the button and
  the flags leave, every run of it, the bare text included, a Text cut at its end, so that the desktop app never wraps
  it and it ends in an ellipsis at the band's edge; then the fault flags, each opening with `│ `, with no Details; the
  flags wrap onto a further line only when they alone outgrow the line beside the button. A pointer resting on the
  button reveals a card of every listed account in the compact words. The fold is kept in the plugin's store, a store
  that cannot be read or written costing only the fold's memory. Details opens and closes the panel, where every
  figure is spelt out and every name is whole.
- **The panel.** Details opens it in a pane (`plugin/hooks/panel.tsx`), in the band's look, what the band says said
  once. At its head stand the window button, *Open WindowTally*, with what the last press came to beside it; then
  only what the blocks cannot say — that the service may not be running, with the status's age, once the status is more
  than five minutes old; the desktop app at its sign-in page; an account the app or the CLI uses that WindowTally does
  not list, by the first eight characters of its UUID; a desktop app that is not running, as `The desktop app is not
  running; start it from the WindowTally window.`; the CLI's condition, as `The CLI does not follow the desktop app: …`
  — and the recommendation, `Next:` and its reason, which names the moment the first account opens or, with an account
  still recommended, room returns, the time left until it added once, ≈ where the moment was inferred (`… Room returns
  ≈Thu 14:00 (in ≈1h 05m).`), as the window's header writes it. The accounts the app and the
  CLI use are otherwise named by their blocks' tags alone. Each account the band lists is a block, in the service's
  order, opened by the band's `● `, orange for the session's own account, judged as the band judges it, and grey for the others; then
  its name, semibold, and its tags in full words, `(desktop app, CLI, use next)`, the first `desktop app, not running`
  while the app is not running, smaller and dim; then, smaller and
  dim, its e-mail where the name is the user's own, the age of its last response, and the age of the reading its
  figures rest on (`read 1m ago`) where both windows rest on one or the 5-hour window has no limit. Under them stands a
  row for each window at the scale of the band's in-use line — the 5-hour figure the panel's largest text, bold, with
  the band's meter and a semibold countdown, the weekly figure smaller with the smaller meter and its reset's weekday
  and time, dim, the warning and error colours on both — each named `5-hour` or
  `Weekly` in one width, in the monospaced face, so that every block's figures stand in one column; a window not
  started says `not started`, one with no figure `running` or `unknown`. An account with no 5-hour limit leads with
  its weekly row, at the scale the 5-hour row otherwise takes, and its 5-hour row after it, at the weekly scale, says
  `no limit`, small and dim, with no meter. Beside a window, smaller and dim, stand the 5-hour
  window's wall-clock reset time, ≈ only where it was inferred, or the time left until the weekly one resets; when it
  is full at this pace; the reading's age where the two windows' readings differ; and beside the weekly one the week's
  use by product (*Use by product*). The plan row, `Plan` padded to the same width with no-break spaces — the plan and
  how far it is paid up, or when it ended, and the profile's word where it says otherwise — closes the block,
  smaller and dim, its warnings in the warning colour, each a Text beside the dim ones, since the terminal dims every
  Text inside a dim one. The other accounts are not dimmed. An account whose plan has ended and that neither client
  uses (*The band*) is instead one dim line under a dim dot — its name, when its plan ended, when its week resets, and
  its e-mail where the name is the user's own — with no figures. At the foot stand the source problems, where there are
  any; where status.json marks accounts hidden, how many, dim, as `1 account hidden: Arrange accounts… in the
  WindowTally window shows it.`; how long ago the status was written, as `Updated 1m ago.`, smaller and dim; and one
  line for the panel's marks, `≈ inferred, not read · ↻ reset`.
  Nothing runs past the pane's width: a line's groups wrap as wholes, a further line starting under the line's own
  content, a block's under the name and a window's under its figure. Sizes and meters are drawn on every surface whose
  element table carries a drawing (`desktop`, `mobile`, `vscode`), and the desktop app raises the pane on `desktop`,
  as it raises the band; on any other surface, the terminal first, which draws one size, the account in use is set
  apart by its name, semibold in the theme's `claude` colour, and its orange dot, the other names plain, no figure or
  countdown takes a weight, the weekly reset stays dim, and no meter is drawn.
- **Passes.** The command line's `once` and `dashboard` and the window's Refresh now each run a pass beside the
  service's. Every pass holds the data folder's `pass.lock` from start to end, waiting up to five minutes
  for one already running (`service`), so two passes never write status.json or the history page at once. A pass
  times each of its phases, its wait for the lock kept apart; the service logs one line for every pass — its counts,
  its time, the history page's share of it and a wait of a second or more — and, for a pass of ten seconds or more
  (`service.SLOW_PASS`), or one that fails, the time of every phase it ran, so a slow pass names where its time went.
- **Changes to the user's files.** Every change of the user's bills file or settings — its read, its change and its
  write — holds `<file>.lock` beside the file, waiting up to ten seconds for another change to end (`files.editing`):
  the window and the command line change the same files, and neither loses the other's change. A bill is replaced or
  removed by its place in WindowTally's own bills file, and only while that place still holds the bill as it was read.
- **Writes.** Every file WindowTally writes for another party is written to a temporary file moved over it in one step.
  The temporary file's bytes are flushed to the disk before the move, in the service and the window (`files`) as in
  the sync (`Write-FileAtomic`), and a write or flush that fails removes the temporary file: NTFS journals a move and
  a file's length but not its bytes, which Windows writes later, so a crash after the move and before those bytes were
  written leaves the file its new length in zero bytes (the sync's `state.json`, on the development machine,
  2026-11-05). On Windows the move is refused while any process holds the file open (measured on the development
  machine, 2026-10-21), so it is retried for two seconds before it fails (`files`; in the sync, `Write-FileAtomic`
  retries such a refusal alike and removes its temporary file when the move fails). Files another program reads
  together are written as one set (the sync's `Write-FileSet`): the CLI's sign-in file, `~/.claude.json` and the stored
  stamp of that file when a stored sign-in is restored, and the desktop app's Cookies file, its journal and
  `config.json` when a login is put in place. Every file of a set is staged first; each is then moved into place with
  its old version kept beside it, and a move refused past the two seconds puts back the files moved before it and fails
  the write, so the program never meets one account's sign-in beside another's profile. A file the user names for the
  window to
  write, the History window's export, goes through the same move but is not retried: what holds it is no reader of
  WindowTally's, and the window's thread must not wait.
- **The window's notifications** say only what the plugin never says, so none repeats a toast: an account usable
  again after every account was at its limit, none recommended and a moment the first opens standing, as the window's
  header judges it; no status written for five minutes, counted from the window's start; a recorded period ending
  within the renewal reminder's days, once per period, of an account status.json does not mark hidden; a source
  problem that stood through two status files, once until it clears. The last two are remembered in `window.json`
  across starts (`notices_model`).
- **Silenced notifications.** While the user's setting (`settings.json`'s `silenceNotifications`) is on, the window
  raises no notification and no Code session raises a limit toast. A notice the window would have raised goes to its
  status line, every notice of one look together, and to its log, and counts as said; a crossing a session would have
  toasted is written to the debug log and recorded as warned of; so turning the setting off brings no stale notice. The
  band still colours a figure at its warning figures. The service carries the setting to the plugin in status.json's
  `notificationsSilenced`, and settings that cannot be read silence nothing, in the window as in the plugin.
- **The logo and the tray icon** (`windowtally_gui/logo_model.py`, `tray_model.py`). The logo is two rings on a dark
  rounded tile with a grey rim: the weekly window the outer ring, in blue, the 5-hour window the inner ring, in green,
  each filled clockwise from the top over a dim track, and at rest filled to fixed amounts (the maintainer's decisions
  of 2026-10-29 and 2026-10-31). It is drawn as pixels from its geometry with the standard library, each size on its
  own pixel grid, every ring and gap a whole number of pixels up to 48 pixels so that the small sizes stay legible, and
  the program keeps no image of it: the window's icon, at the sizes Windows draws a window's icons at on the display,
  the About window's picture, and the Start menu entry's icon file, `windowtally.ico`, which the one-off task's run of
  the window's code draws beside the packages, are each drawn from it. The tray icon draws the same rings live for the
  account in use, the desktop app's, else the CLI's: each ring filled as far as its window is used — empty for a
  window not started, the track alone for one with no figure — and each wearing its own window's level, the logo's
  colour below the window's first warning figure, the palette's warning fill from it and its critical fill from the
  second (*Warning figures*); while every account is at its limit both rings take the critical fill. An account with
  no 5-hour limit is drawn as one ring as thick as the two and the gap between them, its weekly window, so that no
  empty ring reads as a window at zero. The tile's rim wears the account in use's colour, its card's. With no status,
  no account in use, or a status more than five minutes old, the tile is greyed and no ring is filled: nothing on it
  is to be read as a figure. The README's picture, `images/logo.png`, is the logo at 256 pixels as `logo_model`
  writes it, the tree's one copy of the logo; a test decodes it against the drawing, allowing only what another maths
  library's rounding at a ring's end can move, so that a change of the drawing fails the test until the file is
  written again (the maintainer's decision of 2026-10-31).
- **The About window** (Help → About WindowTally; `windowtally_gui/about_model.py`). Beside the logo it names
  WindowTally, its version and its release: the in-code version is 1.0.0 in every release, so the release is named by
  its label, read from the build record a release ships beside its packages, `build.json` (`windowtally/release.py`),
  which `install.ps1` copies into the installed copy; a copy with no record, run or installed from source, says it is
  from source, and one whose record cannot be read says its release is unknown. It shows the copyright line read from
  the licence file beside the packages — the notice the MIT License asks to travel with every copy, which the source
  folder holds and `install.ps1` copies into the installed copy — so that the line is written once, in that file, and
  a copy whose licence is missing or carries no copyright line says so; it says that WindowTally is free and released
  under the MIT License, and that official copies come only from `https://github.com/offcutworks/windowtally`, so that
  a user sold a copy can find out; it says what WindowTally reads and stores — no network request of its own; Claude
  Code's transcripts on this computer read, and each session's use and title, the turns a plan limit stopped and the
  background tasks it started kept in its ledger there; and the sign-ins kept on this computer, sealed for the Windows
  account, handled by the account sync alone, which puts them back into Claude's own apps; and
  it opens the licence and, where a copy ships them beside its packages as a release does, the third-party notices,
  `THIRD-PARTY-NOTICES.txt`. A copy run or installed from source ships neither notices nor a build record, and offers
  no notices.
- **The CLI's sign-in** (in the sync; its description is the canonical statement). The CLI's account is read from the
  `oauthAccount` label in `~/.claude.json`, since the sign-in file names none, and three writers leave three marks: a
  sign-in writes the label and the sign-in file within seconds of each other, in either order; a token refresh, or the
  CLI signing itself out, writes the sign-in file alone; the desktop app's own Claude Code writes the label of the
  account the app signs in to, alone. The sync trusts a label naming another account than the one it trusts only where
  the sign-in file was written within `-SignInWindowSeconds` (30) of the span in which the label appeared — after the
  last look that saw another label, by the look that first saw it — and not by the sync's own restore, or where a
  `claude auth login` has just ended 0 under the launcher (`claude.cmd` then passes `Snapshot -SignedIn`) or as the
  launcher's one-time sign-in, the file written within the window. Every mode that acts on the CLI records its look in
  `state.json` — each watcher tick, each launch, `Snapshot`, `SwitchCli` — and `Status` looks without recording; a
  `state.json` from before looks were recorded, with no earlier look to bound the span, places no foreign label on a
  changed file. A `state.json` that is not a JSON object stops every look, since without it whose sign-in the CLI
  holds is not known: `Watch`'s condition, `Status`'s CLI account (`unknown (<why>)`) and the error of every other
  mode that looks at the CLI name the file and say to remove it, and once it is removed the next look writes it
  again, trusting the label as the first look ever does. A `state.json` the system refuses to read, another program
  holding it, is reported as the read failed and is not called damaged. Any other foreign label was written by another
  program. While the sign-in file is still the one the trusted label
  was last seen with, the file is the trusted account's: once no CLI runs it is stored under that
  account, which keeps its own stored profile, and the CLI follows the desktop app as usual, or — following off, the
  app at its sign-in page, or the app already on that account — that account's label is put back by restoring the copy
  just stored (`Put the CLI's account label back to …`). Once the file has been rewritten after the label appeared,
  whose sign-in it holds is not known: nothing is stored or switched, `Watch` reports the refusal as its condition, the
  launcher and `SwitchCli` refuse (exit 2) and `Snapshot` says so, until the label returns or a sign-in through the
  launcher settles it. A sign-in file without a non-empty OAuth access token and refresh token holds no sign-in, and is never stored, so
  an account's last good copy is never replaced by it; a file that is not a JSON object is a layout the sync does not
  know. A stored profile that is not a JSON object is named and never put into `~/.claude.json`: the restore that
  would put it back fails before anything is written. While the CLI follows a desktop app signed in to the account
  the CLI signed out of, the sync does not put that account's stored
  copy back, since it is the one whose refresh failed or an older copy of it: `Watch`'s condition says
  `The CLI is signed out of <account>: its sign-in has ended. Run claude auth login in a terminal and choose
  <account>.`, the launcher notes it and starts the CLI, which asks for a sign-in itself, and `SwitchCli` to that
  account ends 3. A CLI signed out of another account follows the app as a CLI with no account does. While the CLI
  does not follow — following off, or the app at its sign-in page — a signed-out CLI is not reported, the condition
  being what keeps the CLI from following. `watch.json`'s `cliAccount` still names the label's account. `Status` says
  `(signed out: its sign-in has ended)` after the CLI's account, `unknown (<why>)` for a sign-in file it cannot read,
  and of the label `yes`, `no` (another program's label over the trusted account's file, which the sync puts back or
  follows away from once no CLI runs) or `NO` (whose sign-in the file holds is not known).
- **The two switches.** The sync keeps two switches in `sync-settings.json`, each on until turned off and read as on
  where its key is absent or not true or false, or where the file is not a JSON object, which `Status` reports
  (`Switch settings : unreadable (<why>); both count as on`): *the CLI follows the desktop app*, which `Sync` and
  `Watch` honour (off, they keep
  the CLI where it is and its stored sign-in fresh, and the sync reports no standing condition but a
  sign-in file whose owner is not known, *The CLI's sign-in*), and *one-click switching of the desktop app*, which only
  the window reads. The window turns them through the sync's `Settings` mode, shows its own change until it reads a
  status written after it, then the status's (`switch_model.switches_to_show`), and a pass carries them to
  status.json. Turning the first on again aligns the CLI at the next moment no CLI runs.
- **The desktop app at its sign-in page** is no account's. The sync reads it from the sign-in mark,
  `windowSizeWasSignedIn` false; `lastKnownAccountUuid` then still names the account signed out of, which the sync
  reports as the one the storage names, never as the app's. `Sync` and `Watch` keep the CLI on the account it is on and
  its stored sign-in fresh, as while the CLI does not follow, and report no standing condition but a sign-in file
  whose owner is not known; the launcher says so in `sync.log` alone. A mark the sync cannot read is no word on the
  sign-in: the CLI follows `lastKnownAccountUuid`, while every desktop mode that stores or puts back a login refuses
  such a layout. The watcher's view then names no desktop account and carries
  `desktopSignedIn` false; it writes `desktop_signed_out`, naming the account the storage still names, when its view
  turns signed out, its first view included, and `desktop_account` when the app is signed in to an account it was not,
  the one it left included; a look that cannot read `config.json`, which the app holds while it writes it, keeps the
  desktop half of the view it published. A look that finds the app no longer on the account the last one found also
  judges that account's stored login (*A stored login whose web session has ended*, below). The service takes the
  app's account, or its sign-in page, from the newer of the watcher's view and the desktop timeline's last point, so
  an event a mode writes before the watcher's next look counts at once; status.json then carries `desktopSignedIn`
  false, no desktop account and no account `isDesktop`. The window's header says the app is at its sign-in page,
  every card offers the app's switch as one-click switching
  allows, the account just left included, and the tray draws the CLI's account; the plugin's panel says the same.
  `Status` reads `Desktop account : none: the app is at its sign-in page; its storage still names <account>` and
  `In sync : n/a (no desktop account to follow; the CLI keeps its own)`.
- **The desktop app not running.** The watcher reads whether any of the app's processes runs — listed as a switch lists
  them, by the app's folder outside session 0, never by a process name — only in a look that holds the act mutex, and
  reads `$null`, not known, where the listing fails. A look that finds the mutex held by another act (a switch, an add,
  a store, a start) leaves the view as published and writes nothing, the watcher's first look included, since an act
  closes and starts the app, changes the logins and the CLI and records what it changed as events, and a view read
  half way through it would be newer than those events and wrong; a look that throws publishes its error as the
  condition, and a standing condition is logged once, when it begins. While the app is not running the view carries
  `desktopRunning` false and is written at every look. The service carries it to status.json only while the view is at
  least as new as the desktop timeline's last point — a switch or a start writes its point and starts the app — and no
  older than two minutes, by which a view the watcher stopped rewriting says nothing of an app that may have been
  started by hand since. The app's account stays the one it starts on. The window's header reads `Desktop app:
  <account> (not running)` — `at its sign-in page (not running)` there — and under it the line `The desktop app is not
  running.` stands with the button `Start the desktop app`; the tray's tooltip opens with `Desktop app not running`,
  its menu's `Start the desktop app` is enabled only then, its icon is unchanged and no notification is raised; the
  cards' switch buttons are unchanged. A start, from the button or the tray, runs `StartDesktop` as a switch runs, one
  job at a time, and is never called off: the progress row says `Starting the desktop app…` through the run and after
  it, the header's ` (not running)`, its line and the tray's start withheld, until a status says the app runs, a status
  written 20 seconds or more after the start (`live_model.START_GRACE`) still says it does not, or five minutes pass
  (`STALE_AFTER`). Its end is said in the script's last note; a start asked for from the tray with the window hidden
  raises a notification only where it was not done, the app's own window answering otherwise. The terminal band tags
  the app's account `app closed`, and the panel's head says `The desktop app is not running; start it from the
  WindowTally window.`, the account's tag reading `desktop app, not running`; the plugin never starts the app. A session the app
  hosts runs inside the app, so it never reads the app not running (`status.ts`'s `seenBySession` drops the key), and
  its band and panel say `app` and `desktop app` as for a running app. The `status` command gives the app's account the
  role `desktop, not running`, and with no account `isDesktop`, the app being at its sign-in page, a line `Desktop app:
  not running`.
- **Sessions at work** (`windowtally/registry.py`). A session counts while its registry file names its own process id,
  a session id, a creation time (`procStartFt`, or `procStart` where that is absent or null), a status Claude Code is
  known to write (`busy`, `idle`, `waiting`, `shell`, or none yet) and an entrypoint, and a live process of that id was
  created at exactly that FILETIME; a file whose process is gone, or another process under its id, counts as none, so a
  crashed session stops counting at the next look, with no time limit. A session is at work while its status is
  `busy` — a turn running, or work it delegated still running; `waiting` on the person, `idle` and `shell` are not
  work. A session the desktop app hosts is one whose entrypoint is `claude-desktop`. A file the reader does not
  recognise — not JSON after a second read, a field missing or of another kind, a status it does not know — counts as
  not at work and is named in one source problem, `Claude Code's session registry: <file> <why>; …`, three files
  spelt out and the rest counted. Only names of digits ending in `.json` are opened. status.json's `workingSessions`,
  the window's count and its marks of the working at a switch, its check whether the ledger is behind, the
  Conversations window's sessions at work and the sync's `Status` (`Get-WorkingSessionCount`, which compares the
  process's start time with the entry's FILETIME converted the same way) count the desktop app's sessions at work;
  the keep-awake counts every session at work.
- **Keeping the computer awake** (`windowtally/keep_awake.py`). While the registry names at least one session at work,
  the desktop app's, a terminal's or a scripted run's alike, and `settings.json` does not say `keepAwakeOff`, the
  ledger service holds one Windows power request (`PowerCreateRequest`, reason `WindowTally: a Claude Code session is
  working`), set for the system and for execution and never for the display, which `powercfg /requests` lists under
  SYSTEM and EXECUTION with the service's process (measured on the development machine, 2026-11-11); otherwise it
  holds none. It looks every 2 s on a thread of its own beside the passes, so a hold begins within seconds of a turn's
  start and ends within seconds of the last one's end whatever a pass is doing. The power source is not consulted: it
  holds on battery as on mains. Settings that cannot be read keep the computer awake, the default, the pass naming them
  among the source problems; a refused hold is logged once and tried again at each look; the registry's problems are
  logged when they change. A pass run by the command line or the window holds nothing, and Windows releases the
  request when the service's process ends. The screen still turns off and locks on its own timer, and a lid, the
  power button or the Start menu's Sleep is not stood against. The switch is a check item, *Keep the computer awake
  while Claude Code works*, after *Silence notifications* in the View menu and the tray menu, on unless the settings
  say otherwise; turning it writes the settings and says so on the status line, no pass running, the service reading
  the setting at its next look; a settings file that cannot be written leaves it as it was and says "Not changed" and
  why, and a change made by hand is followed as the silence's is.
- **Switching the desktop app** (`SwitchDesktop`, in the sync). The app's processes are those that run from its
  package folder outside Windows session 0, where the package's Windows service runs and outlives the app; the script
  refuses to run inside that process tree, and refuses a `-DesktopConfig` of its own without a `-DesktopAppDir` of its
  own, so a simulated desktop never closes the real app. It refuses (exit 2), changing no login, when
  the app's flag cache holds the feature flag `96101707` (the app's own multi-account support), when `config.json`
  does not hold `lastKnownAccountUuid` and `oauth:tokenCacheV2` once each as strings and the sign-in mark
  `windowSizeWasSignedIn` once as a boolean, or the mark says signed in and `Network\Cookies` is absent (an app at its
  sign-in page may have none: an add removes it), when the app does not close, and when the target has no stored login
  (exit 3). A switch to the account an app at its sign-in page still names is a switch like any other: only an app
  signed in to the target is already on it. Before it closes a running app the sync waits for a sign-in the app has
  just made to reach its Cookies file (*A sign-in saved before a close*, below). The app is closed by asking every
  top-level window its processes own, hidden ones included, whether the session may end (`WM_QUERYENDSESSION`) and, if
  all agree, telling them it ends (`WM_ENDSESSION`); it is never killed, and the script waits up to `-CloseSeconds`
  (120) until no process of the app is left, since its processes can outlive its quit by a minute and more
  (*Decisions*). A listing of the processes is as old as its start, so only one begun once that time is up refuses;
  where it shows only processes the sync did not ask to close, the note says the app closed but was started again
  within that time. A refusal before the end was announced — the app refused, did not answer, or owns no window to ask
  — says nothing was changed; one after it says no login was stored or changed, but the app was told the session ends
  and may be partly closed. The processes' image paths are read from one CIM query of every process
  (`Win32_Process`), taken after the process list, where each process's own path walks its module list and took many
  times as long on the development machine (2026-10-26); an object that is not a live process, as the tests'
  stand-ins are, and every process when the query fails, is read by its own path. Then the login the app holds is
  stored under its account — unless the closed app's mark says it is at its sign-in page: it then holds no login, and
  nothing is stored for the account it names, whose good stored login stays and whose refused one stays set aside —
  the target's is put back — its two `config.json` values spliced in as raw text and the mark set true, since a login
  is stored only from a signed-in app, every other byte kept, its `Cookies` file replaced after the stale journal is
  removed — and the app is started through its Start menu entry whether or not it was running, so that its log says
  whether it took the login; a failed store of the departing login starts the app again, when it was running, with
  its own login untouched, and a failed restore writes back the bytes `config.json`, `Cookies` and its journal held
  before it, an absent one removed, and starts the app again, when it was running. The stored login is one
  DPAPI-sealed file per account, the two values as raw JSON text and the cookies in base64, read back to check it. The
  sync writes a `desktop_account` event; a switch to the account the app is already signed in to changes nothing and
  writes one all the same, so that WindowTally, if it shows the app elsewhere after a change the watcher never saw, is
  put right, and starts no app. Once it has started the app it reads the app's log (`-DesktopLog`; a simulated desktop
  reads only a log given with it), opened where it ended while the app was closed and read every half second, through a
  rotation: one of the three signed-out lines (*Sources*) ends the switch with exit 5, writes a `desktop_signed_out`
  event naming the target, and sets the target's stored login aside as `desktop-login.refused.dpapi`, which the next store of that account removes. Its note names the refusal from the
  start-up state the restarted app wrote: `sign_in_cookie_present: false` is a login that held no sign-in cookie, stored
  before the app had saved its sign-in; true, a login whose web session had ended, as a sign-out in the app ends it; a
  state not read names no cause. The event, the exit code and the login set aside are the same for both. The window
  shows exit 5 as not done, in the script's words, and runs a pass under them, which keep the status line's warning
  colour through the pass and its result (`actions_model.after`). The start line followed by eight seconds with no
  signed-out line is a done switch; neither within `-SignInSeconds` (60), or no folder for the log, is a done switch
  the sync notes as unconfirmed. A log whose folder exists and whose file does not yet is read from its start once it
  appears. The CLI is not touched: it follows through `Watch`, or is switched on its own by `SwitchCli` while the first
  switch is off, and only while no CLI runs (exit 4 otherwise).
- **Adding an account** (`AddDesktop`, in the sync; the window's *Add an account*, one step). A login can only be stored
  with the app closed, so the add always closes the app, as a switch does, waiting first as a switch does for a sign-in
  just made, and reads whether it is signed in only from
  the closed app's storage: a running app's mark may not yet say what it has just done. The login the app holds is
  stored under its account, then the storage is made to read as signed out with nothing sent to the server — the mark
  set false, then `Network\Cookies-journal` and `Network\Cookies` removed, every other byte kept — since the app decides
  at its start from the sign-in cookie in that file (*Sources*); a step that fails undoes the steps done, the error goes
  on (exit 1) and the app is started again if it was running. The app is then started whether or not it was running,
  its sign-in page being the point, and its log read as after a switch: a signed-out line is the sign-in page reached
  (exit 0); the start line with none for eight seconds is an app that came up signed in all the same (exit 1); no word
  within `-SignInSeconds` is reported as unconfirmed (exit 0). An app found at its sign-in page once closed has nothing
  stored and nothing changed, and is started and read the same way. No `desktop_account` event is written, no account
  having changed; the signed-out line writes a `desktop_signed_out` event at once, naming the account the storage still
  names, so the window shows the app at its sign-in page as soon as the add ends, while an add that ends otherwise
  writes none. The login signed in to at the sign-in page is stored at the next switch away, as every switch stores the
  one it leaves; and since the add ends no web session, the login stored for the account left is taken at the switch
  back, which the account left's card offers: that switch is how an add is called off. Should the app come up signed
  in, an account is added through the app's own sign-out and a sign-in there, which
  ends the web session of the login it leaves (*Sources*): the watcher then sets the login stored for the account left
  aside (*A stored login whose web session has ended*, below) — without a running watcher it is refused at the first
  switch back, which opens the app at its sign-in page (exit 5) — and that account is signed in to once more and
  stored at the next switch away. `SnapshotDesktop` stores the login the app holds, from the command line; it refuses
  an app at its sign-in page before any close (exit 2), and one found there only once closed it starts again, if it
  was running, and refuses.
- **A stored login whose web session has ended** (`Watch`, in the sync). A sign-out in the app ends the web session of
  the account it leaves, and a login WindowTally stored for that account and put back holds that very session where
  the app has not signed in to the account since. The watcher keeps from look to look, in memory, the account the last
  look that held the act mutex found the app on. In each look that holds the mutex it judges the stored login of the
  account the app has left: the account that last look found, where the app is no longer on it — at its sign-in page,
  on another account, or with no `config.json` — and at the first of the watcher's looks to read the app the account
  an app at its sign-in page still names. The judgement reads the login's `savedAt`, then the app's log from a line stamped before that time to its
  end, back through the files its rotations left (`main1.log`, `main2.log` …), and takes the first of the lines of a
  change of sign-in (*Sources*) stamped in `savedAt`'s second or later that names the account: the app leaving its
  sign-in (`false → true`, the account left) ended the stored session, and the login is set aside as
  `desktop-login.refused.dpapi`, as a refused switch sets one aside, its note — to the standard error and `sync.log` —
  naming the account and when the app left its sign-in; a sign-in to it (`true → false`, the account reached) is a
  session of the app's own, and the stored login is kept. No such line, no log or no stored login leaves things as they
  are; a login that cannot be opened or has no `savedAt` read, or a log that no longer reaches back to that time, is
  kept with a line in `sync.log` saying why. A judgement never fails the look, writes no event and changes no key of
  `watch.json` or status.json: the service's next pass turns the account's `desktopArchived` off, and the window's
  switch to it then opens *Add an account*. A switch or an add that leaves an account stores its live login first, so
  its `savedAt` is later than any sign-out before it and the judgement keeps it.
- **A sign-in saved before a close.** Every desktop mode that closes a running app — a switch, an add, a store — first
  reads the app's log (`-DesktopLog`) for the latest sign-in at its sign-in page, the line holding `Login-state
  transition (loggedOut: true`, stamped in the last 35 seconds (`-CookieSaveSeconds`): from the end of `main.log`, and
  back through the files its rotations left (`main1.log`, `main2.log` …) as far as a line that old. Where there is
  one, it waits until `Network\Cookies` has been written at or after the line's second plus one and a further second
  has passed, or until 35 seconds after the line — never more than 35 seconds from now, though the line be stamped
  later than now; `sync.log` says which ended the wait. Where the file has not been so written at its first look, it
  notes `Waiting for the desktop app to save its
  sign-in of HH:MM:SS before closing it...` for the wait. No log,
  as for a simulated desktop given none, no such line, or an app that is not running, is no wait. Times are compared in
  UTC, so a clock change cannot shorten a wait. The wait comes before the note that the app is closing, so the run can
  still be called off while it lasts.
- **Asking before a close.** A switch of the app, or an add of an account, closes the app and ends the Code sessions it
  hosts without the app's own question. The window counts the sessions at work off the registry when the button is
  pressed (*Sessions at work*), or takes the last status's count where that is the larger, and where any is it asks:
  switch anyway, wait and switch (the wait ends when none is at work, and can be cancelled), or cancel; the button of an account whose
  login is not stored explains instead. A switch can be called off until the sync says it is closing the app, the wait
  for a sign-in to be saved included, during which the header says the app is saving its sign-in first; after that the
  Cancel button is disabled, and once the sync says it is starting the app the header says the window waits for the app
  to sign in, or, after an add, for its sign-in page.
- **Taking sessions along at a switch** (`windowtally/sessions.py`, `windowtally_gui/carry_model.py`, the window's
  `CarryDialog`). The desktop app lists a Code session only while it is signed in to the account the session's card is
  filed under, so a switch of the app leaves the account's sessions behind. A session is the account's when the latest
  thing the ledger holds of it, an answer or a limit stop, ran on that account — a standing stop not yet given an
  account leaving the session its latest answer's — and its title, where its transcript gives none, is *Untitled
  session in* the folder its first main answer ran in, as the Conversations window names it; only the desktop app's
  Code tab's sessions are offered, those with an answer or a stop from the `claude-desktop` entry point, within a day
  (`CARRY_SPAN`), since a stopped session that was gone on with was gone on with within hours (measured on the
  development machine, 2026-11-08); a stop stands while no answer came after it. Where the app is signed in, a switch
  of it to an account whose login is stored offers them, with the sessions the registry says are at work, in place
  of the question before a close, which the dialog asks too: the stopped first, the latest first, then the working, then
  those with background work unfinished — a background task the session started within the day (`background_tasks`) that
  no transcript says has ended, *Background work unfinished* — then the rest by their last activity, the stopped, the
  working and those with background work unfinished ticked at the start, and of the rest those active within `JUST_USED`
  (15 minutes) before the switch; with none to offer, the question before a close stands as it was. Each row's last
  column, *Ran with*, says what its session last ran with (`ran_with`): the effort of its latest main answer, as Claude
  Code writes it, then the permission mode its main transcript last named (`session_modes`), in the desktop app's words
  — `default` and `manual` *Manual*, `acceptEdits` *Accept edits*, `plan` *Plan*, `auto` *Auto*, `bypassPermissions`
  *Bypass permissions*, `dontAsk` *Don't ask* — as *max · Auto*, either alone where the other is not known and nothing
  where neither is; another word of letters alone, of at most 32, is shown as written, and anything else not at all. The
  dialog says under the list that the permission mode and effort are set again in each session opened, as that column
  shows. Above the list, a search keeps the sessions whose title holds every word typed, case aside, as the
  Conversations window's does, and beside it stands how many sessions the list shows, of how many, and how many are
  ticked: a session the search hides keeps its tick and is carried with the rest. Where the search shows none, none is
  chosen, so Space ticks no session out of sight; Return in the search goes on to the list, the first session shown
  chosen where no session shown is, and presses no button; Ctrl+F goes to the search. Where a session offered has
  background work unfinished, whatever its state says first, the dialog says under the list that the work does not go on
  there and is to be run again. Before it offers them, where a session of the app is at work, or the registry says one's
  status changed after the last status's `generatedAt` — the start of the pass that wrote it — the window runs a pass
  without the history page (`actions_model.read_sources`), its header saying so with a Cancel that calls the switch off,
  the pass going on to its end; a pass already running is not waited for, the offer then reading the ledger as it
  stands. A switch that ends done (exit 0) hands the sessions chosen on to be opened, through the shell's own opener, as
  `claude://resume?session=<id>` (`LinkQueue`), one at a time, `LINK_GAP` (2 s) apart and the first that long after the
  end; one that ends with exit 5 says the sessions chosen were not opened; a refusal, an error or a cancel says nothing
  of them, which stay on the account still in use. A link the shell cannot open is said on the status line, and in a
  notification while the window is hidden. While the sessions are read or chosen, no other of the sync's jobs begins — a
  switch of either client, an add, a turn of the two switches, a start of the app — since it would take the flow the
  switch is about to need, and a job that began all the same before the switch could start is said, the switch not made.
  While the sessions taken along are being opened, a switch or an add of the app is refused, since it would close the
  app under them, while a switch of the CLI, a turn of a switch and a start of the app may run. The window writes
  nothing of the desktop app's own: the app makes the session's card itself.
- **Every account's conversations** (`windowtally/sessions.py`'s `conversations`,
  `windowtally_gui/conversations_model.py`, `conversations_view.py`). The desktop app lists a Code session only under
  the account its card is filed under and has no list across accounts, so the Conversations window lists every session
  the ledger holds of the desktop app's Code tab or of the CLI — an answer, a subagent's among them, or a limit stop
  from the `claude-desktop` or `cli` entry point — whatever its account, hidden accounts included, the latest activity
  first; the runs of the SDK and of `claude -p` (`sdk-cli` and the like) are left out, and a session with neither an
  answer nor a stop is none. Each session carries its title (`session_titles`, else *Untitled session in* its folder,
  as the switch's dialog names it); its folder, the one its first main answer ran in, none where it has only a
  subagent's answers or a stop; its project, that folder, or the repository of a working copy at
  `<repository>\.claude\worktrees\<name>`, case aside, so every working copy of one stands under one name; its account
  by the rule the switch's dialog takes (above), named as the settings name it, by its e-mail's local part where the
  settings cannot be read, *no known account* where none could be given; its last activity, its latest answer, prompt
  or stop; what its answers, its subagents' included, would have cost at API prices (`cost_usd`), in dollars; and, in
  the last column, *Ran with*, what it last ran with, as the switch's dialog says it (above). The reader reads each
  table once, the answers once more for the latest main answer's effort, grouped by session, and asks `has_table`
  before the tables of titles, modes and stops. The
  search keeps a session whose title holds every word typed, case aside; the account filter offers the accounts by
  name, *no known account* last, and the project filter the projects by name, two of one name told apart by the folder
  each lies in. A session opens on the desktop app's account, as the last status names it, through the app's resume
  link and the shell's own opener, the switch's sessions' path, only where the app's Code tab ran it, and never while
  the app is not running, at its sign-in page or on an account the status cannot name, or while one of the sync's jobs
  runs or a switch's sessions are read or chosen; the line under the list says which, and names the CLI's account for
  the resume command where it is another. Once a session is handed to the app, the window says so and, where what it
  ran with is known, that the app does not keep its effort and may not keep its permission mode, naming what it ran
  with (`handed_words`). The resume command is
  PowerShell's, `Set-Location -LiteralPath '<folder>'; claude --resume <id>`, a quote in the folder doubled, and
  `claude --resume <id>` alone where the folder no longer exists, going on with `--effort` where the session's effort
  is one the CLI takes (`low`, `medium`, `high`, `xhigh`, `max`) and with `--permission-mode` where its mode is
  `default`, `manual`, `acceptEdits`, `auto`, `plan` or `dontAsk`, passed as named, or a bypass, passed as
  `acceptEdits`, with no flag for any other value; a session of the app the registry says is at work gets none. The list is read off the window's thread, in a lane of its own beside the pass's and the History window's, one
  read at a time, an ask while one runs making one more when it ends: when the window opens, on F5, and after each new
  status while it shows, keeping the search, the filters and the session chosen. The line follows the status each
  second; the ages under Last activity are written again every 30 seconds, and the registry read at most once a second.

## Building a release

A release is a zip a user unpacks and installs with `install.ps1`, carrying the interpreter WindowTally runs on, so
that nothing else is installed (*Decisions*, *Choices made in building the release*). It is built from a commit, never
from a working tree:

```
python tools/fetch_build_inputs.py
python tools/build_release.py --label 2026.11.1 [--commit REV]
```

`fetch_build_inputs.py` puts the build's five inputs into the git-ignored `build-inputs/` — CPython 3.14.8's
embeddable package and CPython's full package of the same version, for Tk and the licence page of its documentation,
both from python.org and pinned in `tools/release_core.py`; the wheels of PySide6-Essentials and shiboken6 6.12.0 from
PyPI; and Qt 6.12.0's `qtbase` source archive from download.qt.io, for Qt's licence texts and the list of the software
it incorporates, which the wheels do not carry; the last three pinned in `tools/build_inputs.py` — downloading each
that is missing, or copying it from the folder `--from DIR` names, and putting it in place only when its SHA-256
matches the pin. `build_release.py` downloads
nothing: it checks every input against its pin before it uses it. It needs git, and runs under any Python 3.14 or
later.

The build's order, every step of it that belongs to no one program and the downloading `fetch_build_inputs.py` runs
are `tools/release_core.py`'s, a file kept byte for byte the same in every program its maintainer publishes and changed
in all of them at once. `tools/build_release.py` composes it with what is WindowTally's own: what a release ships, the
Qt it carries, the third-party notices, the build record, and how `tests/TEST_LEDGER.md` names the reds it records. In
order, the build:

- reads the commit's tree through `git archive`, the way a snapshot of the project is made, so a release holds only
  committed files, each as the commit holds it;
- assembles the release: `windowtally/`, `windowtally_gui/`, `sync/`, the plugin's `.claude-plugin/`, `hooks/` and
  `types/`, `extension/`, `install.ps1`, `LICENSE` and `README.md` from the commit; `runtime/`, the embeddable package
  with Tk's module, `_tkinter` and the Tcl/Tk libraries from the full package — the release core's step, which every
  program's runtime takes, though the window no longer uses Tk (*Decisions*, 2026-11-07) — and a path file naming the
  standard library, `Lib` and the release's folder; in `runtime\Lib\site-packages\`, only the files of the two wheels the window
  needs — the bindings and libraries of Qt Core, Qt GUI and Qt Widgets, shiboken6's runtime, the C++ runtime they
  load, Windows' platform and Windows 11 style, and the offscreen platform the suite runs on — each library a file of
  its own, as the wheels hold it, which the LGPL lets a user replace; `THIRD-PARTY-NOTICES.txt`, Python's notices, then
  Qt's, PySide6's and shiboken6's under the LGPL, with the GPL it builds on and where their source is had, every
  component Qt's source lists for Qt Core and Qt GUI's libraries with its licence, and the C++ runtime; and
  `build.json`, the label and the interpreter's version;
- compiles both packages and the runtime's `Lib` to bytecode bound to each source's hash, each recording its path
  inside the release, and refuses a release any of whose files names the folder it was assembled in or the builder's
  home folder;
- runs the whole suite under the assembled interpreter on the commit's tree and refuses the release unless the
  failing tests are exactly those `tests/TEST_LEDGER.md` records in its entries' `tests` fields, the plugin's tests,
  which Claude Code's own runner runs, left out; a test whose entry's `delta` field opens with the mark
  `flaky-quarantine.`, a test red only sometimes, is accepted whether it fails or passes, and a test the ledger names
  both ways, or a mark spelt otherwise, refuses the release (`--no-suite` skips the suite and says the build is not
  verified);
- writes `dist/<label>/WindowTally-<label>.zip`, the release's files at its top level, its entries in one order and
  every file dated the first day of the label's month at midnight, and `SHA256SUMS` naming it, and prints its digest.

The label is `YEAR.MONTH.N`, the N-th release of that month; the in-code version stays 1.0.0.

Two builds with one label of commits holding the same files make the same zip, byte for byte, wherever the repository
and the build lie (two repositories at different paths holding the same files, measured on the development machine,
2026-11-03). To rebuild a release and check it, build the commit the published repository tags with the release's
label, with that label — the suite adds nothing to the zip, so `--no-suite` may skip it — and compare the rebuilt
zip's SHA-256 with the one the release's `SHA256SUMS` gives, as `README.md` checks a download. The inputs are pinned;
what the build does not pin must be held equal: the CPython 3.14.8 running the build, whose zlib compresses the zip and
whose HTML parser writes the third-party notices.

## Decisions

The maintainer's decisions (2026-10-20):

- WindowTally stays passive: nothing is fetched with stored credentials, because using subscription credentials
  outside Anthropic's own clients risks the accounts. Use on other devices therefore shows up only when the
  account is next used here.
- The ledger runs as a background service started at logon.
- The account sync joins this tool; its installed copy is updated and its watcher restarted by `install.ps1`.
- The desktop plugin is installed for every Code session.

The maintainer's decisions on subscription cost (2026-10-21):

- WindowTally learns what each subscription cost and sets it against what the account was used for. What no file on
  the machine says, the user writes down; changes of plan are handled; nothing is fetched, the passive decision
  above standing.
- Bills come both from a bill archive's manifest, read where it lies, and from a bills file of WindowTally's own,
  for a user who keeps no such archive.
- The figures appear on the history page and in the plugin's panel, and the band tags an account due to renew.
- The tests' bills are invented.
- WindowTally's bills file is versioned JSON in its data folder, written by a command or by hand. A manifest is read
  by a module of its own into the one bill model every source reaches, each bill in its own amount and currency, and
  that module is imported only when a source names it, so a publication can leave it out.
- The figures: each account's cost per month on both bases, each bill in the month it was charged and spread over its
  period; its cost per day with a plan; how far it is paid up and the gaps between its recorded periods; the profile's
  plan against the recorded plan in effect; and each plan period's API-equivalent use beside its fee. Since
  2026-10-23 the cost is the plans' US list price, on one basis, and the fee is that price (below).
- The band's renewal tag is a setting, off by default, its days the user's to set.

They leave open showing each period's use of the weekly allowance, and converting between currencies, which would
need an exchange rate and its source; the second was settled on 2026-10-23, none being converted, and is built
(below). Telling an exact 5-hour reset time from an estimated one, left open too, was decided on 2026-10-21 and is
built (below).

Choices made in building it (2026-10-21):

- The sync keeps its PowerShell implementation and runs as its own process; its logic is unchanged: its two
  records were added and its log's timestamps made culture-invariant. Revisit if the CLI should one day pick its
  account by remaining quota.
- The ledger keeps metadata only — times, accounts, sessions, project folders, models, effort, permission modes, token
  counts —
  never message content.
- Data and the installed service live in `%USERPROFILE%\.claude\windowtally`, beside the sync's store, outside the
  source folder, so nothing in it is published with the tool. Never under AppData: measured on the development
  machine, files a process started from inside the Claude desktop app writes under AppData land in the app's private
  storage, invisible to the logon tasks — and the desktop plugin runs inside the app. Files under `~/.claude` are the
  same for every process.
- The service runs from an installed copy under the `pythonw.exe` `install.ps1` is given, a release's own by default,
  and needs only the standard library. Since 2026-11-03 `Install` copies a release's interpreter beside the installed
  packages, and the installed copy runs under that copy (*Choices made in building the release*, below).
- Plugin reading files are deleted seven days after their last change, once ingested.
- Accounts take the history page's colours in the order they were first seen, so an added account never repaints
  the others.
- The plugin's alert thresholds: 5-hour window at 80 % and 95 %, weekly window at 70 % and 90 %; its band is one
  line per Code session in the terminal, its accounts wrapping as whole units on the desktop (since 2026-10-26 in two
  columns, below), with the panel behind it. It registers no command or tool and observes turns, never the model's
  stream, so it adds nothing to a session's model context: a session's `/context` report read the same, byte for
  byte, with the plugin installed as without it (measured on the development machine, 2026-10-21). It runs one
  program, Windows' `schtasks.exe`, and only when its panel's window button is pressed with no WindowTally window
  running: to run the window's logon task, and to ask whether that task is registered when it did not run (the
  maintainer's decision on reaching the window, below).
- The plugin runs from its own copy, `%USERPROFILE%\.claude\windowtally\plugin`, which `install.ps1` adds as the
  folder marketplace `windowtally-local` and installs at user scope. Claude Code reads a folder marketplace's
  plugin in place (`claude plugin list --json` names the copy as the folder it is read from, measured on the
  development machine, 2026-10-21, Claude Code 2.1.302), so editing this folder never changes what sessions run,
  and an Install that refreshes the copy reaches each session at its next start or `/reload-plugins`. Install
  calls the native CLI, not the account sync's `claude.cmd`, which runs a sync first; it re-points a marketplace
  of the same name added from another folder, and reinstalls an entry sessions do not read from the copy.
- A reading is written when a turn that made model requests ends, and whenever Claude Code's measurement reports
  that a plan window changed; the same figures are written again only after a minute, to renew the reading's
  time, and nothing is written while WindowTally's data folder does not exist.
- A warning is judged on the session's own exact readings, for the account the session uses: status.json's
  desktop account in a session the desktop app hosts, its CLI account otherwise. "Once" holds across sessions: the
  highest threshold warned of is kept per account and window in the plugin's store, and a window counts as new,
  warning afresh, when its reset time moved on by at least half its length or its figure fell three points or
  more. A reading past several thresholds of one window raises one toast, for the highest. A session that draws
  nowhere (a `-p` run) neither warns nor records the crossing, leaving the warning to a session someone sees; a
  crossing recorded while status.json could not name the account is taken over by the account's first reading of
  the same window.
- The band reads, per account, `label (app, CLI, next)  5h ≈67% ↻50m  week 69% ↻5d 0h`, the accounts in use
  first. In the terminal it is one line in those words, cut at its edge with the Details button kept in place, and the
  engine folds it there itself. On the desktop the words are compacted — `label (app, CLI, next) 5h ≈67% ↻50m week
  69% ↻5d 0h`, a dim `–` for a window not started, `│ ` opening every unit after the first — and a tag, the fault
  flags and then each account are units that never split, wrapping onto a further line only when they do not fit,
  with Details beside them at the right end of the first line; the tag folds the band (the desktop plugin's
  decisions, below). Since 2026-10-26 the account the session uses stands apart: first on the terminal's line, its
  name in the theme's `claude` colour and the other accounts dim; on the desktop on a line of its own, the other
  accounts' compact units under it and the fold button over Details in a column beside them (below). Only a figure at
  or past a threshold is coloured (the theme's warning colour, its error colour from the second on); a status older
  than five minutes (WindowTally's `status` command's own threshold), source problems and every account at its limit
  are flagged, and every account at or near it in the warning colour rather than the error colour; a missing,
  unreadable or unknown-version status.json is said so in place of the standings; the band gives way to a survey.
  The plugin reads status.json again when its modification time changes, checked every 15 seconds, and redraws
  the countdowns each minute.
- The band shows countdowns, which need no time zone; the panel shows wall-clock times in the zone the plugin's
  environment reports, marked UTC where it reports none but UTC. In status.json, `estimated` covers a window's
  figure and its reset time together, and `anchorExact`, on every window, says whether the reset time came from a
  plugin reading; so the panel, the `status` command, the history page, the window and the recommendation's reason
  mark a reset time ≈ only where it did not, whatever the figure's estimate, and the band and the window's tray
  tooltip, which write a countdown after its figure, mark a countdown only where no figure stands before it. With
  every account at its limit, the reason marks the moment the first opens ≈ where that reset time was inferred, with
  every account at or near it the moment room returns likewise, and
  `recommended.reliefExact` says the same of it, so the countdown to it on the band, in the panel and in the window
  is marked ≈ alike: only where it was inferred, or where the file does not say.
- Bills are read whole on every pass and copied nowhere, so the ledger's schema is unchanged. Revisit should a bill
  source be sometimes out of reach.
- The settings live in `settings.json` in the data folder, written in UTF-8 by `bills source` and `bills remind`, so
  a path the console's code page cannot spell survives (Windows PowerShell 5.1 garbled a non-ASCII path its console's
  code page could not spell, measured on the development machine, 2026-10-21); `install.ps1` takes no setting.
- A bill names its account by e-mail, and every account WindowTally knows with that e-mail takes the subscription,
  since the ledger keeps accounts whose folders are gone. Revisit should a billing e-mail differ from the sign-in one,
  or two accounts on this machine share an e-mail and pay separately: the bills could not tell them apart.
- A manifest gives only the vendor `Anthropic Claude`'s paid rows, one bill per invoice, from its single invoice row.
- A source with one broken bill is refused whole: a source read in part shows totals that look right and are not.
  Since 2026-11-04 a broken bill is left out alone and named, and no total is given while one is (*Rules*, *What was
  not read*).
- The accrual spread each bill over its own printed period and did not split a change of plan's bill between the
  old period's tail and the new period: so spread, the figures matched the monthly accounts of the bills they were
  checked against, a change of plan being a proration bill of its own (2026-10-21). Since 2026-10-23 no figure reads
  a bill's amount: the plans' cost at list price replaced both bases, and a period cut short by a change of plan
  counts only its days in effect (*Rules*, Subscription cost).
- The profile's plan is read from `organizationType` and its rate-limit tier as Claude Code 2.1.302's bundle spells
  them, and 2.1.310's still did on 2026-10-31; any other value is not compared.
- The plugin reads status.json version 3 only and reports a file of an earlier version as another version: one
  release installs the ledger service and the plugin together, and the service writes the file afresh on every pass
  it completes, so a file of an earlier version lasts only until the new service's first completed pass.
- The renewal reminder is computed by the service, which writes `renewSoon` per account and `renewalReminderDays`
  into status.json; the plugin only draws it.
- The command line prints a character its output stream cannot encode as `?` instead of failing (measured on the
  development machine: a piped stdout takes the console's code page, which cannot encode every character a command
  prints).
- The history page's *Subscriptions* section follows its daily cost charts: a summary, a monthly chart of the plans'
  cost at list price stacked by account in the accounts' own colours, the table of that cost per month, the plan
  periods and the gaps; every charted value is also in a table (since 2026-10-23; until then a chart of the spread
  cost and tables of cost and of payments per month). Each account's card gains its plan and a *renew
  soon* badge.
- Bill source paths are compared however they are spelt — relative to the data folder or absolute, in any case,
  through `..` — and kept normalised.

The maintainer's decisions on the window (2026-10-21):

- WindowTally gets a desktop window of its own — a live monitoring window, not a static page, carrying function
  buttons, where what the user has to fill in, such as the bills, is entered too — beside the history page and the
  plugin's band, which stay.
- The window shows the whole history as well as the live standings.
- A tray icon and the full window, started into the tray at logon; the Start menu entry; a keep-on-top switch.
  Closing the window hides it in the tray (since 2026-10-28 it minimizes it while the tray icon is missing, below).
- Live, every figure status.json carries: each account's two windows with their ≈ marks, resets, pace and reading's
  age, its plan line, its roles and its renewal tag; the status's age, the accounts in use, the sync's condition, the
  recommendation and the source problems. Since 2026-11-09 a reading's age, a plan's days left and the source
  problems are said only when they matter, and the accounts in use only where the cards cannot say them (below).
- The history in the window: the history page's content over a span the user chooses — 7 days, 30 days, 6 months or
  all — computed read-only from the ledger once the page is split into a figures layer and an HTML layer that both
  draw from, the page's own output unchanged; its charts drawn by Tk, with no new dependency (painted with Qt since
  2026-11-07, below).
- The buttons: refresh now; the history page, written afresh and opened (until 2026-10-28, below); record a bill; the
  bills listed, with change and remove for WindowTally's own bills file and a further source's bills read-only; add
  or stop reading a bill source; the renewal reminder on or off and its days; the data folder; the source problems,
  their count always shown (since 2026-11-09 only while there are any, below) and their list behind a button. Not offered: switching accounts (the passive decision;
  since 2026-10-24 the window switches them through the account sync, below), starting or stopping the service.
- Notifications only for what the plugin never says (*Rules*), none at a warning figure; the plugin unchanged.
- The static history page stays; the window's History page button writes it afresh and opens it. The button and its
  menu entries went on 2026-10-28 (below), the History window exporting what it shows instead; the page stays.
- Help → About gives the name, the version, and that the tool reads only files already on the computer, sends no
  network request and reads no credential. Since 2026-10-31 it also carries the copyright line, the licence and the
  official copies' address, and its words on what is read cover the whole tool, the account sync's sealed sign-ins
  among them, and since 2026-11-03 it names the release (*Rules*, *The About window*; below).
- The window follows Windows' light or dark app mode as it changes, in the history page's palette, each account in
  its history-page colour; since the theme control (below), it does so by default, and the user may keep it light or
  dark instead.

The maintainer's decisions on the History window (2026-10-21):

- It is a window of its own, reached by a History button beside History page in the main window, by File → Show the
  history and by the tray menu's History, and kept on top with the main window, as the Bills and sources window is;
  the history page and its button stay (the button until 2026-10-28, below).
- One scrolling column in the history page's order — weekly usage, cost by account, cost by model family per
  account, subscriptions, time with every account exhausted, sessions, models and effort, coverage — under the span
  buttons, which stay in place; no account cards and no recommendation, which the main window shows live. Since
  2026-10-23 the summary heads the column, since 2026-10-28 the measure of what a full window holds follows the
  subscriptions, since 2026-11-02 the tokens follow the cost by model family, and since 2026-11-11 the cost by context
  follows effort (below).
- On its first opening the content's place says it is computing, the line above it naming the span, 30 days; on a
  change of span the content shown stays, that line says which span is being computed, the span buttons stay usable
  and the last choice wins; the result replaces the content in place with the time it is as of. The history is
  computed on opening, on a choice of span and on Recompute, never on a clock.
- Cost columns per day over 7 and 30 days, per week from Monday over 6 months and all, the model families' charts
  alike; the weekly usage line chart is drawn over the span as it is.

The maintainer's decision on reaching the window from a Code session (2026-10-21), built on 2026-10-22:

- The plugin's Details panel carries, at its head, a button that brings up the WindowTally window, so a user reaches
  it without typing a command; the band keeps its one Details button. Not taken: the button beside Details on the
  band; no button, and a desktop shortcut written by the installer.
- The button asks a running window to show itself through the window's request file in the data folder, which the
  plugin already writes into; with no window running it has Task Scheduler run the window's logon task, so the window
  lives outside the session — a program the plugin starts itself ends with the session or after ten minutes at most —
  and asks again once the window holds its lock; with the task not registered it says to run the installer. The
  plugin so runs one local program, its only one.

Choices made in building it (2026-10-22):

- The button, *Open the WindowTally window*, heads the panel whatever status.json holds, with what the last press came
  to beside it, dim, and *Bringing up the window…* while a press is carried out; a press while one is carried out is
  ignored, and a press left unfinished by a reload of the plugins is forgotten at the session's next start.
- A press writes `window.request` and gives a running window 1.5 seconds to take it, three of its looks. With the
  request still there it runs `schtasks.exe /Run` on the logon task `\WindowTally\Window`, named by its path under
  the system folder the environment names. The task starts the window into the tray, and the window, taking its lock,
  clears a request left from before it ran; so the request vanishing within 20 seconds says the window holds its lock,
  the only sign of it the plugin can read, since it opens no lock and deletes no file. The press then writes the
  request again and waits up to 20 seconds more for the window to take it. Revisit should the request be found never
  taken after the task ran, or the window starting slower than that.
- A running window too busy to take the first request in time also has the task run; the task ignores a start while
  its window runs (`-MultipleInstances IgnoreNew`), and a second window finding the lock held only asks the first to
  show itself and ends, so the words said after it claim no start: *The window was shown.*, or that it is running and
  shows itself once ready.
- Where `/Run` fails, `/Query` is asked, and only then: Task Scheduler answers in the system's language and exits 1 for
  every failure, so the panel says the task cannot be found, with Task Scheduler's own first line and that the
  installer registers it, only where `/Query` fails too, and otherwise passes on what `/Run` said.
- The program is run through the engine's `$.process.run`, which the desktop app's Claude Code build (2.1.299) gates
  to no surface, and whose spawning hides a child's console window (read from that build's engine on the development
  machine, 2026-10-22). Revisit should the button be seen failing on the desktop, or a console window flashing.
- The desktop app draws a pane's tree as given, the head's row ending in a button included: unlike the band's site, a
  pane's site reshapes no row (measured in the desktop app 2.42304.0.0's bundle, 2026-10-22). Revisit should a later
  bundle give panes a reshaper.

The maintainer's decisions on the main window after seeing it (2026-10-21), built on 2026-10-22:

- One Bills button in the row in place of Record a bill and Bills and sources, which open the same window; Record a
  bill stays in the Bills menu and the tray menu.
- Compact cards: two lines per window — its figure and meter, then when it resets, the pace and the reading's age on
  one line — and the plan on one line with this month's cost (until 2026-11-04, below); every word stays shown rather
  than moving into a hint. Since 2026-11-09 the meter is a ring, and a reading's age and a plan's days left are said
  only when they matter, never moving into a hint either; since 2026-11-11 the card is the tightened one, its rings
  beside the two windows' names and figures and each window's line across the card under them (below).
- A theme control beside Keep on top: a drop-down of three — follow Windows, light, dark — following Windows by
  default as before, the same three in the View menu; the choice is remembered across starts and applies to every
  window of WindowTally. Since 2026-11-11 the theme and Keep on top are set in the View menu alone (below).

They leave open the About window's copyright line, licence and the address of the official copies, decided on
2026-10-31 (below).

The maintainer's decisions in building them (2026-10-22):

- The default size: a card's least width 32 lines of the default font, which holds a window's second line whole at
  its usual length, and the window opening 68 lines wide, two cards abreast and the third below them, all in view.
  Since 2026-11-11 a card's least width is 22 lines and the window opens 70 lines wide, three cards abreast (below).
- The theme control: the caption *Theme* before a drop-down at the row's right end, immediately left of Keep on top,
  its items *Follow Windows*, *Light* and *Dark*; in the View menu, after Silence notifications, a separator and the
  same three as radio items. Since 2026-11-11 the row, its caption, its drop-down and its Keep on top box are gone, the
  View menu's items the theme's one place (below).
- The compact card: its title row; the e-mail and the last response; per window its name, figure and a meter filling
  the rest of the line (since 2026-11-09 the two windows as concentric rings beside the figures, no bar on a card,
  and since 2026-11-11 the tightened card, below), then when it resets, when it is full at this pace and the reading's age; then *Plan*, the plan,
  this month's cost at list price (until 2026-10-23 this month's cost and what was paid, and none since 2026-11-04,
  below), the profile's word on the
  plan on the same line, wrapping only where the card is too narrow.

Choices made in building them (2026-10-22):

- The row's one Bills button opens the Bills and sources window, its hint naming what that window holds: recording a
  bill, every bill recorded, the bill files read and the renewal reminder. The Bills menu and the tray menu keep both
  entries unchanged.
- The theme choice is kept in `window.json` (`"theme"`: `system`, `light` or `dark`; absent or unknown, it follows
  Windows; the file's version unchanged), not in `settings.json`: only the window reads it, while `settings.json` is
  read by the service and carried to the plugin. Revisit should the plugin's band or the history page be wanted to
  follow it. The drop-down and the View menu's items show one choice, so each shows what the other set (the View
  menu's alone since 2026-11-11, below); a choice
  applies at once to every window of WindowTally, which share one theme, the tray menu and the title bars included, and
  Windows' mode is read every three seconds only while the choice follows it.
- The window opens 68 by 40 lines: measured at 200 % on the development machine, three compact cards fit 68 by 38 with
  nothing to spare, and two lines more leave room for the header's lines on the CLI's condition and a notice. Since
  2026-11-11 it opens 70 by 30 lines (below).
- A card line is pieces of text, each in its own colour, joined on one line while they fit the card's width; from the
  first that does not fit, it and every piece after it go whole onto a line of their own without the join, so no word
  is hidden (`card_model.flow_places`).
- The account's colour dot is drawn as a picture, each pixel taking the account's colour as far as the disc covers it,
  sampled four by four within the pixel, and mixed with the card's surface rather than left partly transparent, so it
  looks the same whatever Tk does with a picture's alpha; Tk on Windows draws a canvas oval without smoothing. Revisit
  should the dot be drawn on a surface other than the card's. Since 2026-11-07 Qt paints the dot with a smoothed edge,
  and no picture of it is drawn (below).
- The window's icon is drawn at the sizes Windows draws a window's icons at on the display — its large and small icon
  sizes, 32 and 16 pixels at 100 % and 64 and 32 at 200 % — rather than at 32 and 16 always, which Windows scaled up;
  the picture is the tray's, unchanged. Revisit should the larger icon's corners be found jagged. Since 2026-10-31 the
  picture is the logo at rest, drawn at each size on its own grid (below).

Choices made in building the window (2026-10-21):

- The window is a package of its own beside the service's, standard library and Tk only; the service never imports
  it, so the service stays free of Tk and a publication needs nothing beyond Python. The History window's charts are
  drawn on Tk's canvas. Revisit should a chart need a charting library. Since 2026-11-07 the window is drawn with Qt
  Widgets through PySide6, its charts painted with Qt, and needs PySide6 beside Python; the service still needs the
  standard library alone (below).
- Its live figures are status.json's alone, the plugin's contract, read again only when the file's modification time
  changes (looked at every two seconds), whatever the file held; only a read that failed is tried again at the next
  look. Countdowns are redrawn each second. A reader holding the file makes the service's replace wait, so the window
  holds it as rarely as it can.
- Refresh now runs one pass in the window's own process, on a thread of its own, under the pass lock, as `once` does
  beside the service. Revisit should the service be the ledger's only writer: the window would then ask the service
  for a pass through a request file, a new contract.
- Every change to the bills or the settings goes through WindowTally's own functions and checks; one that cannot be
  written says "Not recorded" or "Not changed" and why, never silently.
- The window reads no credential and touches nothing of the account sync's store; the bill form's accounts come from
  status.json. Only a pass the window runs reads the accounts' profiles, as the service's passes do.
- Accounts take their colours by the history page's own rule, over a read-only ledger connection. Where the ledger
  cannot be read, the order of status.json's list stands in, said once in the status line, and the ledger is tried
  again with each new status file.
- A figure at a warning figure is written in a text colour of its level, each at 4.5:1 or more on every surface it is
  written on (the suite measures them), beside a meter in the level's fill; a meter below the first figure takes the
  history page's `good` fill, as the page's meters do (since 2026-10-23, below; since 2026-11-10 the page's cards draw
  rings and no meter, below).
- Percentages are rounded half up, as the band rounds them (62.5 reads 63 %), so the window and the band agree; the
  history page and the `status` command round half to even, a difference left as it was.
- One window per user: a second start writes `window.request` and exits, and the running window shows itself; no
  socket is opened.
- The logon start is a scheduled task, and the Start menu entry is written by a one-off task (`\WindowTally\Setup`,
  removed once it ran), because the Startup and Start menu folders lie under AppData, which a script run inside the
  desktop app cannot write where Windows reads (the measurement above). The logon start is therefore turned off in
  Task Scheduler, or by Uninstall, not among Task Manager's startup apps.
- A left click on the tray icon shows the window and never hides it: Tk reports a double click as two clicks. Since
  2026-11-07 the icon is Qt's, and a double click shows the window too.
- The Bills and sources window stays on top with the main window while keep-on-top is on: it opens from the tray while
  the main window is hidden, so it is no transient of it.
- The window logs to `window.log` in the data folder, since pythonw has no console; an unexpected error in the window
  is logged and said in its status line.
- Light and dark: ttk on the `clam` base, every state map clam gives the window's widget classes taken over from the
  window's colour roles (read from Tk 9.0.4's clam, 2026-10-21); each combobox's list coloured on its own; Windows
  asked for the dark title bar; the menu bar drawn as the window's own buttons, so it turns dark, which a menu bar
  Windows draws does not. Since 2026-11-07 Qt draws the window in its Windows 11 style (Fusion on an earlier Windows),
  wearing the roles through one
  palette and one style sheet, and the title bar follows the mode through the colour scheme Qt asks Windows for
  (below).
- A change in the Bills and sources window is said under the part it was made in, and kept at the head of the main
  window's status line while the pass it starts runs and after it. A step of the reminder's days is written 0.8
  seconds after the last step, and at once on Return or on leaving the field.
- An amount's comma is read only as a thousands separator (1,408.63); any other comma (12,50) is refused, the decimals
  asked for after a point, never read as 1250.
- Work the window runs off its own thread always reaches the window when it ends — its result or its failure, on the
  window's thread — and is over before either is handed on, so a failing handler cannot leave a job running.
- The history page, the History window and its export draw one figures layer, `windowtally/history.py`, which holds
  every figure of their sections and the words they share, the notes included; `dashboard` keeps the markup of the
  page and of the export, the page's own ranges and the words naming them or the command line, the account cards and
  the recommendation. The split left the page's output unchanged byte for byte on three synthetic machines, compared
  once (2026-10-21), and adding the export left it so again (2026-10-28), rather than kept as a golden page in the
  suite, which would turn every later change of the page into a test change; the suite checks instead that the page
  says what the figures say, and that the export's headings are the window's.
- A span's days: 7 and 30 days count today and the days before it; 6 months start on the same day six calendar
  months back, or on that month's last day; all starts on the day of the ledger's first response or reading.
  Revisit should a rolling 182 days be wanted.
- Every section follows the span but the subscriptions, which cover every recorded bill whatever the span: a month's
  total, a plan period and a gap are whole only over every bill. Revisit should the subscriptions be wanted narrowed.
- The History window computes with no account profile, since the window reads the sync's store only through a pass
  it runs: its subscription summary has no profile column, which the live cards carry. Where two accounts share one
  e-mail it names the subscription as the page does, by the account whose profile is on this machine, taken from the
  accounts the last pass recorded in the ledger as having one (`Ledger.profiles_on_machine`). It reads the bills as a
  pass does, and its Coverage lists the source problems status.json carries, the list the page is written with.
- The history is computed in a lane of its own beside the window's passes, never queued behind one: it only reads,
  and a pass writing the ledger beside it does not block it. A Recompute asked while the same span is being computed
  is followed by one more computation, the result read before the ask shown meanwhile.
- The chosen span is kept while the window runs and starts at 30 days; it is not written to `window.json`. The
  History window opens 60 by 44 lines of the default font, within 90 % of the main monitor's working area, centred
  from side to side on it, and its place is not remembered; Escape hides it and F5 recomputes.
- A chart's mark shows, under the pointer, what the page's tooltip says. A table is as tall as its rows and the wheel
  over it scrolls the view around it; one wider than the view scrolls sideways.
- Over 6 months and all, a cost column is a week from Monday, labelled by its first day, its pointer words giving its
  first and last; a note says the first and last columns hold only the span's days. The weekly usage chart's ticks
  are days within ten days, Mondays within ten weeks and month starts beyond; a tick label that would overlap the one
  before it is left out at any width.
- Every day and month name the page and the window write comes from WindowTally's English tables (`timeutil`), never
  from `strftime`, so the page reads the same under any locale.
- The main window's default size holds its row of buttons whole (68 lines wide since the compact cards, above; since
  2026-11-11 the buttons stand at the header's line and the window opens 70 lines wide, below); a
  window with a remembered place keeps it. The span buttons take clam's `Toolbutton` state maps over in the window's
  roles, and the model families' fills are window roles, for the charts. Since 2026-11-07 the spans are one segmented
  control, the chosen one filled (below).

Choices made in finding a tray icon Windows refused (2026-10-28). Measured on the development machine (2026-10-28), a
window started at logon in the same second as Explorer had its task run and logged no error, and no icon was in the
notification area: Tk 9 asks Windows to add an icon once, when it is made, ignores a refusal, and adds it again after
Explorer re-creates the taskbar only where that first add succeeded (Tk 9.0.4's library and Tk 9's source, read on the
development machine), so a window started hidden was out of reach until a second start, and said nothing. Since
2026-11-07 the icon is Qt's, and the choices below stand for it, asked and made again through Qt (below).

- Windows, not Tk, is asked whether the icon is there: an icon modification that changes nothing, sent to Tk's window
  for its icons under the id Tk registered the icon by, which Windows accepts only for an icon it holds
  (`tray_view.Tray.present`). Revisit should a Tk release report a refused add itself.
- While the icon is missing it is made again through Tk, every 5 seconds, so that Tk's own record of it is right and
  its re-add after a taskbar re-creation works from then on; with the icon held it is asked about again every 60
  seconds, so an icon lost later is found too. Revisit should the look be found costing the window's
  responsiveness.
- One refusal is looked at again 5 seconds later before anything is done, and two running make the icon missing:
  Windows also refuses while Explorer is too busy to answer, and making a shown icon again for that would flicker it.
  An icon refused at logon is so made again 5 seconds later than it could be. Revisit should those seconds be found to
  matter.
- A window started hidden shows itself once the icon has been missing for two minutes, counted from the first refusal,
  and says why on its status line and in `window.log`; a window already shown is told without being shown. At logon
  the icon usually arrives at the next try, so showing the window at once would put it up at most logons. Revisit
  should logons be found where the icon needs longer.
- While the icon is missing, closing the window or File → Hide the window minimizes it rather than hiding it; where
  the icon was never made, closing the window still quits it and File → Hide the window minimizes it. In both cases a
  notification, a switch's answer from the tray included, goes to the status line and the log
  (`Notice, no tray icon: …`), as a silenced one does; whether the icon is there is asked again at each of these, the
  clock's last look being up to a minute old. The icon's return is said on the status line where its absence was.
- No delay on the logon task's trigger: a delay guesses when Explorer is ready, slows every logon, and still says
  nothing when the guess is wrong. Nor a wait for the notification area before the icon is made: its window existing
  stands in for the icon being accepted, which the checks above ask directly.
- The decision lives in `tray_check_model.py`, with no toolkit, the calls to Windows in `tray_view.py`, by the
  package's `_model` / `_view` rule; the suite covers the former and the structure Windows reads, and the window's use
  of it is checked by eye, as the tray icon is (*Caveats*).

The maintainer's decisions on the desktop plugin (2026-10-21):

- On the desktop surface the band lays out each account as a unit that never splits: the units wrap onto a further
  line only when they do not fit, and Details sits at the right end of the last line. Since 2026-10-22 Details stands
  at the right end of the first line, and since 2026-10-26 under the fold button, a unit wider than the room by itself
  wrapping within itself (below).
- Folded, the band's tag stands alone: Claude's own usage indicator already shows the account in use, and the plugin
  is for the view across accounts. The maintainer's decision on the folded desktop band (2026-10-31, below) keeps this
  ground and replaces the rest: the room beside the tag carries the other accounts.
- The panel says how a weekly reset time was made only beside one, never where no weekly reset time exists.
- A small tag folds and unfolds the band. On the desktop, a pointer resting on the tag reveals a card above the band
  with every account; the card goes when the pointer leaves the tag and the card, and clicking the tag pins the view
  by unfolding the band. No card can be pinned: a pinned card would cover the conversation's last lines. Revisit,
  dropping the card for the click alone, should it be found flashing on the pointer's way to the prompt, or drawn
  badly.
- status.json writes `anchorExact` on `fiveHour` too, meaning its reset time came from a plugin reading, and every
  surface marks a 5-hour reset time ≈ only where it is not exact. Its version stayed 2, both readers already
  accepting the field on any window; since 2026-10-23 it is version 3 (below).
- An account the desktop app uses before the CLI has signed in to it stays as it is: WindowTally shows no account
  before the sync has stored its profile, and the user is told to sign the CLI in to it once (*Rules*, No known
  account).

Choices made in designing it (2026-10-21):

- The terminal band is unchanged: it already draws the one-line design above, cut at its edge, and the engine gives
  the terminal band a fold of its own — the `[-]` it draws beside the band and the chord ctrl+x ctrl+a, bound in both
  Claude Code builds (2.1.302 and 2.1.299, read from the engine on the development machine, 2026-10-22), while the
  desktop app's frontend has no such fold — so the plugin's fold tag is the desktop's alone.
- The tree states the desktop layout itself rather than relying on the desktop app's reshaping of the band, which is
  undocumented: measured in the desktop app 2.42304.0.0's bundle (2026-10-22), it reshapes a row whose trailing
  children are buttons into a block of text and a row of actions, and lets a text's nested runs break between them.
- The fold's state is remembered across sessions in the plugin's own store: the plugin reads and writes only
  WindowTally's data folder and that store, and runs no program but the window button's `schtasks.exe` (above).
- The folded tag still carries the fault flags — a stale status, source problems, and every account at its limit
  with when the first opens, or at or near it with when room returns: a fold hides figures, not faults.

Choices made in building them (2026-10-22):

- The tag reads `▾ Accounts` unfolded and `▸ Accounts` folded, a plain dim button at the band's start: it names what
  the band holds and which way a press turns it. Revisit should it prove unclear. Since 2026-10-26 it reads
  `Accounts ▾` and `Accounts ▸`, over Details in a column of its own when the band is unfolded (below).
- Folded, the tag stands with the fault flags beside it, and, where status.json gives no standings, the problem
  that says why; Details is not shown. Since the maintainer's decision of 2026-10-31 on the folded desktop band
  (below), the accounts stand between the tag and the flags. Unfolded, Details' place and the units' words are the
  maintainer's decision on the band's use of space (below), built on 2026-10-23, which replaced this choice's Details
  at the right end of the last line and a unit cut at the band's edge, and which the two columns of 2026-10-26
  replaced in turn (below).
- The card exists only while the band is folded, since unfolded the band already shows every account; it gives
  each account two lines — its label and tags, then its two windows — so that a line fits the app's hover card, at
  most 360 px wide. Revisit should the card prove cramped, or be wanted unfolded too.
- The fold is read from the store when a session starts or reloads its plugins, so a session already open follows
  a fold made in another at its next start or `/reload-plugins`, not at once. Revisit should every open session be
  wanted to follow at once: the store would then be read at each status poll.
- A store that cannot be read or written costs the fold's memory, never the band: the failure is logged to the
  debug log, a press still folds the band for the session, and the band and its polling go on.
- status.json's `anchorExact` is written for every window from one rule in the service, so each weekly window's
  value is the one it had before. The history page's weekly row and the recommendation's reason read the weekly
  window's exactness from its reset schedule, which agrees with `anchorExact` on every standing a pass produces.
- The band keeps marking a countdown only where no figure stands before it, judged by `anchorExact`, and the window's
  tray tooltip, which writes a window as the band does, follows it.
- With every account at its limit, the recommendation's reason marks the moment the first opens ≈ where that reset
  time was inferred; the countdown to it was left unmarked on the band, in the panel and in the window until
  status.json said whether it was read, which the maintainer's decisions on silencing the notifications settled
  (`recommended.reliefExact`, below).

The maintainer's decision on the desktop band's use of space (2026-10-22), built on 2026-10-23:

- Details moves to the right end of the band's first line, outside the area the accounts wrap in, so it never takes
  a line of its own; the fault flags follow the tag, as they stand when the band is folded; and the units' words are
  compacted where the meaning holds — a shorter mark for a 5-hour window not started, narrower separators — so more
  accounts fit a line. Not taken: the layout as it stood. For Details' place it replaces the decision above that puts
  Details at the right end of the last line; the accounts still never split, so a line still ends where the next
  account does not fit.

The maintainer's decisions in building it (2026-10-23):

- The compacted words: a dim `–` for a window not started, the 5-hour and the weekly window alike; one space between
  an account's parts; `│ ` and one column between accounts — `alpha (app, CLI, next) 5h ≈67% ↻50m week 69% ↻5d 0h │
  beta 5h – week ≈96% ↻3d 4h`. The terminal band keeps the full words (`not started`, two spaces, `  │  `), and the
  panel still spells every window out.
- The card the folded tag reveals takes the same compact words.

Choices made in building it (2026-10-23):

- The tag stays inside the area the units wrap in, so a further line starts at the band's left edge and the column
  under Details is empty below the first line. Revisit should the tag be wanted as a column of its own.
- The fault flags are units like the accounts: a flag that does not fit beside the tag wraps as any unit does.
  Revisit should the flags be found crowding the first line.
- `│ ` opens every unit after the first in the area, the fault flags included, not only the accounts: with one column
  between units, it is what tells the flags and the first account apart. Revisit should the flags be wanted marked
  otherwise.
- Folded, the band is as it was: the tag and the fault flags, no Details. With no standings, the problem stands in the
  area and, unfolded, Details beside it. The maintainer's decision of 2026-10-31 on the folded desktop band (below)
  puts the accounts between the tag and the flags.
- Details stands in a Box of its own that never shrinks, beside an area that grows to push it to the band's right
  end, so no row ends in a Button for the desktop app to reshape. Revisit should that reshaping be seen acting on the
  band.
- The area sets no minimum width and clips nothing: a single unit wider than the band less Details is not cut by the
  plugin, its drawing left to how the desktop app sizes the area, since clipping the area could clip the card drawn
  inside the tag. Revisit should Details be seen pushed out or overlapped at a narrow width.

Since 2026-10-26 the unfolded desktop band is two columns, the fold button over Details on the left (below), which
replaces the tag in the area, the fault flags as units after it, Details at the right end of the first line and a
single unit wider than the room left to the desktop app; folded, the band kept them, its button's label aside, until
the maintainer's decision of 2026-10-31 on the folded desktop band (below).

The maintainer's decision on attribution (2026-10-22):

- The corrected attribution derives again the whole history it can judge, back to the desktop app's first kept
  sample, not only the latest use.

Choices made in correcting attribution (2026-10-22):

- A request is booked to the account its client was signed in to at that moment, and a desktop session's owner line
  is taken only before the timelines begin (*Rules*, Attribution): the owner line lags the desktop app, while the plan
  figures that rise with the sessions' use are the app's account's (*Sources*). Revisit should a day be found on which
  the owner's figures rose with a session's use while the app's evidence named another account.
- A reading's weekly reset is checked against each account's schedule as most of its readings carry it, never as its
  latest reading does, so a few misbooked readings never redefine a schedule; a reset on no account's schedule — a
  schedule moved, an account with no readings yet — leaves the timeline's answer. Revisit should an account's weekly
  schedule be found moved onto another account's.
- A CLI session's readings follow the CLI timeline, as its responses do: a reading belongs to the same stream of
  requests.
- The rule's version is kept in the ledger's meta table, and a ledger derived under another rule is derived again
  whole at its next attribution, so the installed service repairs the live ledger when it first runs a new rule; the
  accounts a pass read a profile for are kept there too. Neither needs a schema change, the assignments being derived
  values, not facts. Revisit should a second per-account fact need recording each pass: a column, with its migration.

The maintainer's decision on silencing WindowTally's notifications (2026-10-22), built the same day:

- The window offers a setting, off by default, that silences WindowTally's notifications: while it is on, the window
  raises no Windows notification and the desktop plugin raises no limit toast in any Code session. Silenced means not
  raised at all, not raised quietly — Tk's `tk sysnotify` takes a title and a message only (Tk 9.0.4, measured on the
  development machine, 2026-10-22), so a notification without its sound or banner would need another notification
  API and a dependency the window does not carry. What the window would have said still reaches its status line and
  its log; the band still colours a figure at its warning figures. Not taken: notifications kept in the notification
  centre without sound or banner; a switch per kind of notice; silencing the window alone. Since 2026-11-07 a
  notification goes through Qt's tray icon, given a title and a message as before.

The maintainer's decisions in building it (2026-10-22):

- The service carries the setting into status.json, as it carries the renewal reminder, rather than the plugin
  reading `settings.json` itself. `settings.json` version 1 gains the optional key `silenceNotifications`, absent
  meaning off; status.json gains `notificationsSilenced` and, with it, `recommended.reliefExact`, which says whether
  the moment the first account opens again was read, as `anchorExact` says of a reset time; neither file's version
  changes.
- The switch is a check item, *Silence notifications*, in the View menu beside Keep on top and in the tray menu; the
  main window carries no control of its own for it.

Choices made in building it (2026-10-22):

- Switching it writes the settings and runs a pass at once, so status.json carries the change to every Code session
  once that pass ends, at the plugin's next look at it; a settings file that cannot be written leaves the switch as
  it was and says "Not changed" and why. The window reads the settings again whenever their modification time
  changes, so a change made by hand is followed; such a change reaches the Code sessions with the service's next pass.
- The key is written only while it is true, as the reminder's days only while the reminder is on; any value but true
  or false refuses the file, as a misspelt key does.
- Settings that cannot be read silence nothing, in the window as in the plugin, since a pass writes
  `notificationsSilenced` false for them and names them among the source problems: the two surfaces never disagree.
- The plugin keeps the silence the last status.json it read whole gave it: a read that failed, as an atomic replace
  can make one for a poll, or a file gone, leaves it as it stood. A session that has read no status.json whole raises
  its toasts.
- A silenced notice counts as said, and a silenced crossing as warned of, so turning the setting off replays nothing.
  Revisit should the warnings be wanted given after all.
- A status.json without `reliefExact` or `notificationsSilenced` is read as inferred and as not silenced: a file that
  does not say is treated as the safer reading.
- The setting has no command-line switch: the window and a hand edit set it.

The maintainer's decisions on the History window's scrolling (2026-10-22), built the same day:

- A notch of the wheel scrolls as many lines of the default font as Windows' wheel setting says, three unless the
  user changed it, and a screen at a time where the setting says so; the main window's cards, in the same scrolling
  frame, scroll the same way.
- A chart's mark says what it is once the pointer has rested on it for Windows' hover time, 400 ms unless the user
  changed it; nothing is said while the view scrolls, and the chart keeps one window of words, moved and reworded
  rather than made again for each mark.

Choices made in building them (2026-10-22):

- Measured on the development machine on the shown window at 200 % (2026-10-22), the eleven tables, drawn as ttk
  Treeviews, were what made each step of the wheel slow to repaint, and the charts' few hundred canvas items were
  cheap. The tables are drawn on canvases instead (`table_model`, `table_view`), looking as before — the headings on
  the face colour above rows on the field colour, a total row in bold, a frame, a sideways bar where a table is wider
  than the view — and Shift with the wheel scrolls a wide table sideways. Not taken: drawing the charts as pictures.
  Revisit should the tables be found looking or behaving worse, or a measurement show the charts dominating. Each step
  of the wheel still held the window for about 40–60 ms at 200 % (measured on the development machine, 2026-10-22).
  Since 2026-11-07 Qt paints the tables and the charts from the same layouts (below), and since 2026-11-10 a table
  stands as a panel on the cards' surface (below).
- Every unit the wheel sends counts: what does not make a whole line is carried to the next turn, kept exactly
  whatever the setting, and dropped when the wheel turns the other way, as Windows does; notches arriving before the
  window repaints are scrolled in one step. Windows' wheel setting is read at each step and its hover time as the
  pointer reaches a mark, so a change to either applies at once.
- Strokes, radii, gaps, offsets and small insets are given in pixels at 100 % and scaled by the display's scale
  (its dots per inch over 96), not by the font, as display quantities: the charts' lines, gridlines and baseline,
  their round marks and the marker's ring, the gap between stacked column segments, the tick labels' offsets and least
  gap, the chart's margin beside its value labels, the legend's swatches, the span buttons' gap, the pointer words'
  place, padding and border, and, through the shared theme, the padding of every window's buttons and the side
  padding of its lists' headings. Revisit should the user's font size be set apart from the display scale.
- A lone reading, the extra-reset marker and the legend's ring are drawn as pictures with a smoothed edge by the code
  that draws a card's dot (`disc_model`), clear beyond the mark so a gridline under it is cut to a circle; the card's
  dot is drawn as before. Lines, columns and gridlines stay canvas items, square to the axes. What size alone leaves:
  a line's round caps and joins are canvas strokes, unsmoothed, their steps the same size on the screen as at 100 %.
  Since 2026-11-07 Qt paints the marks, the lines with their round caps and joins, and the columns with smoothed
  edges, the gridlines and baseline square to the axes, and no mark is drawn as a picture (below).

The maintainer's decision on the window's regions, colours and contrast (2026-10-23), built the same day:

- Every fault measured set right at once: the cards and panels stand apart from the page, the page's note text is
  legible, a meter below the first figure is coloured as on the history page, the meters start at one place on every
  card, a window's name stands on its figure's baseline, and a read-only drop-down no longer looks selected after a
  choice. Not taken: setting right only some of them; recording them only.

Choices made in building it (2026-10-23):

- The palette is the history page's, so the page changes with the window: in light `page` #f0efeb (was #f9f9f7) and
  `muted` #6b6964 (was #898781), in dark `surface-1` #222220 (was #1a1a19) and `muted` #989690 (was #898781). A card
  or panel stands at 1.12:1 against the page in light (was 1.03) and 1.22:1 in dark (was 1.12), and `muted`, the page's
  note and tick text, at 4.5:1 or more on the page and the surface in both modes (was 3.4:1 in light); the suite
  measures both. The window's light `hover` becomes #e8e7e1 (was #efeee9), which the new page would otherwise match.
  Revisit should the page read too dark, or the cards still blend into it.
- A meter below the first figure takes `good`, the history page's fill at that level (`dashboard._severity_color`),
  rather than the grey it had, so every surface marks a figure the same way (*Rules*, Warning figures). Revisit should
  a neutral meter be wanted below the first figure. Since 2026-11-10 the page's cards draw rings and no meter, and
  that function is gone (below).
- The recommendation stands on a band of its own, the window's `advice` role (light #e6eef8, dark #172536), its accent
  bar unchanged; its text, `ink` or, with every account at its limit, `critical-text`, reads at 4.5:1 or more on it
  (the suite measures them). The history page's recommendation keeps the surface colour. Revisit should the page's be
  wanted tinted too. Since 2026-11-10 the page's stands on the same band (below).
- A card's edge is drawn in `baseline` rather than `grid`, so it shows on the darker light page.
- Every card's figure column is as wide as the widest figure or state a window shows — `≈100%` in the figure's font,
  `not started`, `running` and `unknown` in bold, and `no limit` since 2026-10-31 (below) — so the meters start at one
  place whatever the figures say.
- A window's name is raised by as much as the figure's font descends below its baseline beyond the name's own font, so
  the two stand on one baseline.
- A read-only drop-down — the Theme control (until 2026-11-11, below) and the Bills and sources window's — keeps its
  field colour when focused
  and selects its text in that colour, showing focus by its border alone: clam's selection fill read as text left
  selected after a choice.

The maintainer's decisions on the history's summary and on subscription cost in US dollars (2026-10-23); the
subscription cost at list price, status.json version 3 and the main window's totals built the same day, and after
them the summary at the head of the History window and the history page:

- The History window and the history page begin their history with a summary of the figures most looked at, and the
  main window gives this month's totals across the accounts. Nothing of either goes into the plugin. A measure of what
  a plan's limits hold is no part of it: it waited on a study of its own until the maintainer decided, on 2026-10-28,
  that it be built without one, and is built (below).
- A subscription's cost is shown at its plan's US list price, in US dollars, wherever WindowTally shows one — the
  cards, the History window, the history page, the summary, the main window's totals, the `status` command and the
  plugin's panel — so that it stands beside the API-equivalent figures in one currency, the most standard, with
  nothing converted: the plans are priced in US dollars. What was paid in a bill's own currency is no
  longer shown. A bill keeps the amount and currency it was charged in, shown only where bills are recorded or listed
  (the Bills and sources window, `bills add`, `bills --list`), and the software builds in no currency of its user's:
  no default, order of suggestions, example or rule favours one. This settles the conversion between currencies left
  open on 2026-10-21 (above): none is converted.

The maintainer's decisions in designing them (2026-10-23):

- The summary, over the span shown: the API-equivalent cost in all and per day; the plans' cost at list price, with
  the API-equivalent cost as a multiple of it; each account's share of the API-equivalent cost; the model family that
  cost the most, with its share; and the hours in which every account was exhausted. The figures are computed once in
  the figures layer (`history`), which both surfaces draw. In the History window it is the first block of the
  scrolling column, seen on opening and after each change of span; on the history page it follows the account cards
  and the recommendation, before the weekly usage, over the page's thirty days. On both it is a row of tiles, a small
  caption over a large figure, wrapping where the width ends.
- The main window's totals stand on a line of their own under the one naming the accounts the desktop app and the CLI
  use: the month's API-equivalent use across the accounts, the plans' cost at list price and the one as a multiple of
  the other, such as `This month, all accounts: $1,284 API-equivalent · $300 plans at list price · 4.3×`. Since
  2026-11-04 the line begins `This month:` (below).
- The list prices are Anthropic's US web prices as checked on 2026-10-23: Pro $20 a month, or $200 a year billed
  annually; Max 5x $100 and Ultra $200 a month, monthly only — Ultra then named Max 20x, its price unchanged by the
  renaming of 2026-10-31 (below). WindowTally holds them as it holds the API prices (`pricing`) and fetches nothing;
  they change when the prices do.
- A plan's cost at list price spreads each recorded period's price evenly over its printed days; a period cut short
  by a change of plan counts only its days in effect, and the new plan its own period from the change. So it says what
  the plan time held is worth at the US list price, never what anyone paid: an upgrade from Max 5x to Ultra on the
  tenth day of a 30-day period counts $100 × 10/30 + $200 = $233.33, what a US customer at list price is charged in
  all — $100 at the start, then $200 less the $66.67 the old plan had left. A top-up or a settlement of extra usage has
  no list price and counts in no figure; it is listed with the bills. The plan periods give each period's list price
  where they gave its charge, and its API-equivalent use as a multiple of that price, every period's rather than only
  a fee in US dollars; the last bill the subscriptions' summary names is given without its amount.
- status.json becomes version 3: an account's this-month subscription figure becomes its plans' cost at list price,
  in US dollars, and the document gains this month's totals across the accounts — the API-equivalent use and the
  plans' cost at list price. The window and the plugin read version 3 only and change together; the plugin's panel
  writes an account's this-month figure at list price, its one change for this.
- A bill still records the amount it was charged; whether it should, now that no figure uses it, was left open, and
  the maintainer decided on 2026-10-27 that it does (below).

Choices made in designing them (2026-10-23):

- The cost per day divides by the span's days elapsed, today counted by the part of it gone, so the rate does not fall
  at each midnight. Shares and the leading family are by API-equivalent cost, the use with no known account a share of
  its own.
- The summary's plans' cost follows the span, counted on the bills' UTC days that fall on the span's dates, so it
  stands beside the API-equivalent cost of the same days; the subscriptions section below still covers every bill.
- The month of the main window's totals and of status.json is the UTC month of the bills' days, as each card's
  this-month figure is. Its totals count every response of the month, the use with no known account included, and
  every subscription bill once, an e-mail no account here has included: summing the cards would count twice the plan
  of two accounts sharing an e-mail and leave out a bill whose e-mail no account here has.
- The history page's thirty-day sections count the same days: its sessions, models and effort tables, counted from
  thirty days of hours before now, move to the cost charts' local days, so the summary's total is what the tables add
  up to.
- In the table of hours with every account exhausted, a first week the span begins inside says from when it counts,
  as a week the ledger's record begins inside already does.
- Should a list price change, the table gains each price's first day, and a period is counted at the price of its own
  days.

The maintainer's decision in building the subscription cost at list price (2026-10-23):

- A subscription period that is neither one calendar month nor, for Pro, one calendar year is priced by the day at the
  monthly list price, twelve months to 365 days, and named as a problem of the bills.

Choices made in building it (2026-10-23):

- status.json version 3 names an account's figure `thisMonthListPrice`, and the totals `thisMonth.apiEquivalent` and
  `thisMonth.plansAtListPrice`: the first null only where the writer read no ledger, the second while no bill source
  exists, and since 2026-11-04 also while some bill could not be read.
- The plan periods' *At list price* is a period's cost counted on its days in effect, so a period cut short by a change
  of plan shows the part counted, and its API-equivalent use is given as a multiple of that. Revisit should the
  printed price be wanted there.
- The main window's totals are written in whole dollars and the multiple to one decimal, as the decision's example
  writes them; without bills the line gives the API-equivalent use alone, and the multiple stands only where the plans'
  cost is above nothing. Each account's figure — on its card, in the panel, from `status` and `bills` — is written to
  the cent, `this month $… at list price`.
- The `status` command gains no totals line, and the plugin reads none of the document's totals: the decision gives
  the totals to the main window alone.
- No currency is favoured: every bill's amount is written after its currency's ISO code (`EUR 90.00`, `USD 200.00`),
  with no table of signs; the bill form suggests only the currencies of the bills it lists, alphabetically; the
  help of `bills add --currency` names none. Revisit should the decision be read as leaving how an amount is written
  alone.
- The list prices are held in `pricing` beside the API's and the periods' rule in `billing`; the cost note the History
  window and the history page print is written from the price table, so it follows a change of price. Every plan a
  bill may name has a list price, which the suite checks rather than each pass.
- A month of a subscription renewing on the 29th to the 31st is a month after a short month too: from 28 February to
  31 March is one month of a subscription renewing on the 31st, as bills print it.
- A period starting inside another without raising the plan, already named a source problem, cuts the earlier one as
  a change of plan does, so the earlier period's remaining days count nothing. Revisit should such a cut period be
  wanted to keep its days.

Choices made in building the summary (2026-10-23):

- The window's summary is headed *Summary*, its span named on the status line above the column; the page's is headed
  *Summary, last 30 days*, as *Weekly usage, last six weeks* names its own range. Revisit should no heading, or
  another word, be wanted.
- Its tiles, in order: *API-equivalent cost*, *API-equivalent per day*, *Plans at list price*, *API-equivalent ÷
  plans*, an account's *share* for each account, *Costliest model family* and *Hours with every account exhausted*.
  Money is written as the page writes it, to the cent below $1,000 and in whole dollars above, the plans' cost first
  rounded to the cent half up; the multiple to one decimal with ×; shares in whole percent; the family as its name and
  share (`Opus · 97%`); the hours to one decimal as the exhausted table writes them, *no data* where the ledger knows
  nothing of the windows. Revisit should the maintainer word them otherwise. Since 2026-11-02 a *Tokens* tile follows
  the plans' tiles, or the cost per day without bills, and comes before the shares (below). Since 2026-11-04 the last
  two read *Top model family* and *Hours all exhausted* (below).
- Every account shown has a share tile, 0% where it has no use; the use with no known account has one only where it
  has any; without priced use the shares and the family read —. Revisit should tiles be wanted only for accounts
  with use.
- Without a bill source there is no plans' tile and no multiple; with bills but none on the span's dates, the plans
  read $0.00 and the multiple stands only where the plans' cost is above nothing, as the main window's totals line
  does.
- The span's plans' cost is computed in the figures layer (`history.plans_cost`) from each period's list price per
  printed day (`billing.Period.daily`), and `billing` is unchanged. Revisit should `billing` come to own costs over a
  range.

The maintainer's decision on the service's priority (2026-10-23), built the same day:

- The service's and the window's logon tasks run at Task Scheduler priority 5, the normal priority class beside the
  programs the user starts, rather than at Task Scheduler's default, 7, which ran them below normal, at low I/O
  priority and at memory priority 2 (measured on the development machine, 2026-10-23). `install.ps1` sets the tasks'
  priority. Not taken: the service raising its own priority at start; leaving it as it was. The gain is unproven:
  under a load of 24 busy processes, then of 4 writers, a pass run by hand took alike at either priority, while the
  service's own pass at priority 7 took several times as long during that load (measured on the development machine,
  2026-10-23). It takes effect at the next `install.ps1 -Mode Install`, whose Status names each task's priority.
  Revisit should the I/O and memory priorities be found not to follow the class.

Choices made in building it (2026-10-23):

- The service logs a line for every pass, where it logged only a pass that read something new; a pass's source
  problems are logged beside that line rather than instead of it. The log's three files hold 2 MB each (were 512 KB),
  about a month at a pass a minute. Revisit should the log's size matter more than its reach.
- A pass of ten seconds or more logs its phases (*Rules*, Passes): a pass that writes the history page can take as
  long, so such a pass names the page's time. Revisit, to twenty seconds, should those lines prove too many.

The maintainer's decisions on switching accounts from the window (2026-10-24), built on 2026-10-25:

- The sync has a switch, *the CLI follows the app*, on by default.
- The desktop app and the CLI have switching controls of their own, apart from each other.
- Switching the desktop app in one click has a switch of its own, on by default.
- The window asks before it switches where Code sessions are working: the app's own question before it closes is
  bypassed by the way the sync closes it.
- Switching is on the main page, on the account cards, and not only in menus.
- The contract grows by optional keys of status.json and of the sync's state, with no change of version, and by a new
  session-markers file at version 1. A reader that finds a key absent reads it as: the CLI follows, one-click switching
  unavailable, no stored login, no session at work. Since 2026-11-15 the session-markers file is withdrawn (below).
- Layout: each card has its switch button or buttons at its title row's right end; an Accounts menu in the menu bar
  holds the two switches, *Add an account* and the switch menus; the tray menu mirrors it with the recommended account
  listed first (since 2026-10-26 in the one order every list follows, below); the header line says the mode,
  following or apart.

Choices made in designing it (2026-10-24):

- The sync script owns the switching: the window starts it as a process and never touches a credential, as the code
  that handles credentials stays out of the process that reads the transcripts (*Parts and processes*).
- With the CLI following the app a card has one button, *Switch here*, and no CLI button, which is left out and not
  greyed; with the two apart a card has an app button and a CLI button. A button is left out on the card of the account
  its client already uses: a button that cannot be pressed is clutter.
- The recommended account's button is the accent.
- The app is closed gracefully only: the end-of-session request goes to its windows, the sync waits, and if the app
  does not close the switch is abandoned and the user told. Never a kill, which could corrupt the login the sync is
  about to store.
- The app is started again through its Start menu entry, `Claude_pzs8sxrjxfjjc!Claude`.
- A switch is refused, and says why, where the app's own multi-account support is present (the feature flag `96101707`
  in `%APPDATA%\Claude\fcache`) and where the app's storage is not laid out as expected. It never guesses.
- The stored logins are DPAPI-sealed, in the sync's store beside the CLI's.
- Turning the CLI's following on again aligns the CLI at the next moment no CLI runs, with no question.
- Turning one-click switching off keeps the stored logins, so turning it on again is instant.
- A marker whose process is gone does not count: a client that crashed leaves no session at work. Since 2026-11-11
  the window counts off Claude Code's session registry, whose file names its process (below).
- The questions: with Code sessions at work, *Switch anyway*, *Wait and switch*, *Cancel*; with a CLI running, *Switch
  when idle*, *Cancel*. What a switch is doing is shown in the header, and can be cancelled.
- An account with no stored CLI sign-in has the window open a terminal for `claude auth login`.

Choices made in building it (2026-10-25):

- The app's processes are those that run from its package folder (`-DesktopAppDir`), never any Claude process with a
  window that is not the CLI: that can be the client a Code session runs in, which a switch would then close. The
  script refuses to run inside that tree and refuses a simulated desktop that has no folder of its own, and its tests
  give every call a folder that holds no real app and a stand-in launcher.
- An account with no stored desktop login is refused with exit 3, and the window explains how it is stored, rather than
  the sync signing the app out for it: how the app's storage looks signed out has not been measured, and a switch does
  not guess. Revisit once it has been, when *Add an account* could be one step. Since 2026-10-26 it is (`AddDesktop`,
  below).
- The sync gains three modes the window needs: `SnapshotDesktop` (store the
  login the app holds, the first login of an account), `SwitchCli` (the CLI alone, refused while it follows the app and
  while a CLI runs) and `Settings` (the two switches), with exit 3 for a missing stored login and 4 for a running CLI,
  which the window tells apart from other refusals.
- The app is asked through every top-level window its processes own, hidden ones included, since a window hidden in
  the tray is not the process's main window; all must agree before the end is announced, and one that refuses or does
  not answer cancels it for all. An app that was not running is not started; since 2026-10-26 a switch starts it
  (below).
- A stored login is one sealed file holding the two `config.json` values as raw text and the cookies in base64, written
  and read back whole, so the two halves never come from different moments; the cookies are refused above 1 MB. The
  older `oauth:tokenCache` and the per-organisation `dxt:*` keys are left as they are. Revisit if an account's data
  shows under another after a switch.
- Markers carry no process id, which the plugin's sandbox does not offer: the heartbeat (15 s) with a freshness of two
  minutes stands for it, so a client that dies is counted at work for two minutes at most. They are written only for
  sessions the desktop app hosts, and only for main-loop turns: a terminal's session ends with nothing when the app
  closes, and a subagent's turn runs inside the main one. The window counts the sessions off the markers when it asks,
  and takes the larger of that and the status's, so the question is asked once too often rather than missed. Since
  2026-11-11 it counts them off Claude Code's session registry, taking the larger as before (below), and since
  2026-11-15 the plugin writes no markers (below).
- The window shows the two switches as the user last set them until a status written after the change says the same,
  so a menu and the cards follow a click at once and a status older than the click cannot undo it.
- The accent is the recommended account's first button alone, so a view has one primary action (since 2026-11-12 the
  one filled button of every window, the other windows' default answers quiet, below); a card's roles moved
  from its title row to its second line to leave the row to the buttons. The dialogs' default is the cautious answer
  (*Wait and switch*, *Switch when idle*); the tray menu's switch menus list the recommended account first, the Accounts
  menu the status's order (since 2026-10-26 both the one order, below).
- A switch asked for while the window is hidden in the tray says how it ended in a notification, unless the user
  silenced WindowTally's or the tray icon is missing, the status line then carrying it (since 2026-10-28, above).
- A dialog's window is made topmost after it is placed and modal: set before, the window was moved to Windows'
  default place (measured on the development machine, 2026-10-25).

The maintainer's decisions on the desktop app's processes (2026-10-25):

- The app's processes are those that run from its package folder outside Windows session 0. The package also holds a
  Windows service that starts at boot, owns no window in the user's session and does not exit when the app does;
  counted among the app's processes it made a closed app look running (a switch refused, "owns no window to ask to
  close") and a closing app look unclosed (a wait of `-CloseSeconds`, then a refusal and no restart), with no login
  file touched either way. Windows runs services in session 0 and the app's own processes ran in the user's session
  (measured on the development machine, 2026-10-25), so the rule needs neither the service's name nor its path. The
  script's own session was rejected as the test: run from another session, a remote desktop one, it would take a
  running app for absent and rewrite its login files under it, a worse failure than the one fixed. Revisit should the
  package start a persistent helper of its own in the user's session: a switch would then refuse after the wait, with
  nothing changed, and the rule would need refining.
- A store of the departing login that fails once the app is closed starts the app again, if it was running, as a failed
  restore does, rather than ending the switch with the app closed. Revisit should a failed store be better left with
  the app closed, so that it is noticed.
- The refusal after a timed-out close still says nothing was changed, though by then the app's windows have been told
  the session ends. Since 2026-10-26 the switch waits about two minutes for such an app, and a refusal past that says
  the app was told to close and may be partly closed (below).
- The tests stand in for the service with an entry added to the process list the script reads: a real service needs
  administrator rights and registers a system object, and the suite registers nothing. The entry is a session-0 process
  of the app's folder whose id belongs to no live process, which a wrapper hands to the script and notes in a marker
  file, so that a test cannot pass for want of the script ever reading the list; a separate test classifies a made-up
  list after proving that nothing real matches the test's folder. The tests that start a stand-in app need a user's
  session and skip in session 0, where the script no longer looks for the app. Revisit should a runner in session 0
  ever exist: the desktop tests would then fail there rather than skip.

The maintainer's decisions on a stored login the desktop app refuses (2026-10-25), the second built the same day and
the first on 2026-10-26:

- WindowTally gains a way to add an account that does not end the stored login of the account left: with the app
  closed, the sync stores the login it leaves and leaves the app at its sign-in page without the app's own sign-out,
  and the window's *Add an account* becomes one step. It waited on a measurement of how the app's storage looks signed
  out.
- After a switch the sync reads the restarted app's own log: a sign-out there ends the switch with an exit code of its
  own, 5, and sets the refused login aside, so that the account counts as having none; no word in the log in time is
  a switch that could not be confirmed, and still done; the window shows exit 5 as not done, with how to sign in. No
  key is added to status.json: setting the login aside turns the account's `desktopArchived` off.

Choices made in building it (2026-10-25):

- *Add an account* says that the sign-out ends the web session of the account left and that the first switch back
  opens the app at its sign-in page: until the one-step add, the dialog would otherwise describe a procedure whose
  result it misstates. Storing the login the app holds stays its first step: that login, refused once, is what brings
  the app back to the account left, at its sign-in page, without a second sign-out. Since 2026-10-26 the add is one
  step (below).
- The check runs only after a restore, on the app started again, and finds a refusal only in a signed-out line, never
  in silence. The start line with no signed-out line for eight seconds is a done switch: the signed-out lines
  measured came within a second or two (*Sources*). The wait ends after 60 seconds. A log whose folder is absent is
  no check at all, so a log that moved costs no wait; a folder with no log yet is waited on. An unconfirmed switch is
  done, the sync's log says it could not be confirmed, and the window says the switch was made, which is true.
  Revisit should a real start write a signed-out line later than eight seconds after its start line, or one while it
  stays signed in, or should the window be wanted to say "unconfirmed".
- Exit 5 is shown in the script's own words, which say whether the login could be set aside, in the status line's
  warning colour and with no pass after it, whose own words would replace them; the service's next pass, within about a
  minute, carries the set-aside to the cards. Revisit should the window learn to keep a warning's colour through a pass.
  Since 2026-10-26 it does, and a pass follows exit 5 at once (below).
- The refused login is kept as `desktop-login.refused.dpapi`, read by no reader and removed by the next store of that
  account. Revisit should refused logins be worth keeping longer.

The maintainer's decision in building the first of them (2026-10-26):

- The sync's contract grows by the mode `AddDesktop`, which ends 0, 1 or 2 and adds no exit code; `SwitchDesktop` and
  `SnapshotDesktop` act differently on an app at its sign-in page, their codes unchanged; every desktop mode refuses a
  `config.json` without its sign-in mark as a boolean; the note of exit 3 names `AddDesktop`; and the window's *Add an
  account* has one action, *Open the sign-in page*, beside *Sign the CLI in…* and *Close*.

The maintainer's decision in building it (2026-10-26):

- WindowTally is to show an app at its sign-in page as signed out — no account named as the app's, and a switch
  button on the card of the account just left — built as a change of its own, since it changes what the sync
  publishes, what the service writes and what the window shows, together; it was built the same day (below). Until
  then, while the app was at its sign-in page, the sync went on reading the app's account from `lastKnownAccountUuid`
  alone: the CLI stayed on the account left, WindowTally named that account as the app's, and the window offered no
  switch back to it, which `SwitchDesktop -Account <that account>` from a terminal outside the app made.

Choices made in building it (2026-10-26):

- The mode is named `AddDesktop`, after the window's action and beside the other desktop modes.
- The signed-out state is made locally: the mark set false and `Network\Cookies` removed with its journal, the login
  values and every other byte of `config.json` kept. A start after a sign-out that had reached the Cookies file reported
  no sign-in cookie and came up signed out, while a start with a restored cookie whose web session had ended reported
  one and was refused (*Sources*): the app decides at its start from the cookie in that file. Revisit should the app
  come up signed in after an add (the mode then ends 1 and says so), or the switch back to the account left be refused
  (exit 5).
- The whole Cookies file goes, not the sign-in cookie alone: picking one cookie out needs an SQLite engine in the sync
  and the cookie's name, which was not measured, and the account left's whole file is in its stored login. Revisit
  should an add be found to lose a sign-in beyond Claude's own that the user relies on in the app.
- The sync writes the mark itself rather than leaving it to the app's next start, so the storage reads as signed out
  even should the app never rewrite the mark at such a start, or never be started. The mark is written before the
  cookies go, and the steps done are undone should a later one fail, so the storage never reads as signed in without
  its cookie, which a later store would file as the account's login, and a failed add leaves the app as it was.
- The add closes the app and reads its mark only once it is closed, even where a running app's mark already says it is
  at its sign-in page: a running app's mark may not yet say what the app has just done. Revisit should the app be
  measured to write the mark at once at every sign-in, and the close of an app already at its sign-in page be worth
  avoiding.
- The add starts the app even where it was not running, unlike a switch: its sign-in page is the point. Revisit should
  an app that was not running be wanted left closed here too. Since a later decision of the same day a switch starts
  it too (below).
- An app that came up signed in after an add is an error, exit 1, in the script's words, rather than a code of its
  own: the agreed contract adds none, and the window shows anything but 0 as not done, in the script's words.
- A restore that fails writes back the bytes the app's files held before it, whichever way the app was left: one path,
  and an app at its sign-in page has no stored login to put back.
- The window's store of the app's login goes with its button rather than staying uncalled: every add and every switch
  stores the login it leaves, so nothing in the window runs `SnapshotDesktop`, which stays for the command line.
- An add's pass is said in the script's last note, the window's own words where it wrote none: only the script knows
  whether the sign-in page was reached or could not be confirmed, and whose login it stored.
- A `config.json` without the mark refuses every desktop mode, as any layout the script does not know does.
- For adding an account this replaces the choices of 2026-10-25 that refused a switch to an account with no stored
  login rather than signing the app out for it, until the signed-out storage was measured, and that had *Add an
  account* describe the app's own sign-out.

The maintainer's decision in building the signed-out view (2026-10-26):

- The contract grows without a change of version: `watch.json` and status.json by `desktopSignedIn`, written only as
  false, and `events.jsonl` by the kind `desktop_signed_out`, which the watcher writes when it sees the app at its
  sign-in page and a desktop mode when it reads that in the app's log, so the window shows it the moment an add ends.
  Not taken: the watcher's view alone, which would have added no event kind but left the account left named as the
  app's for up to about a minute after an add.

Choices made in building it (2026-10-26):

- While the app is at its sign-in page the CLI stays on the account it is on, its stored sign-in kept fresh as while
  it does not follow, and the launcher says so in `sync.log` alone: a signed-out app has no account to follow, signing
  the CLI out too would only leave it unusable, and a note on every launch would repeat a normal state. Revisit should
  the CLI be wanted stopped while the app is signed out.
- The desktop timeline names no account from a `desktop_signed_out` event to its next point, and a response there takes
  its session's owner line, else no account: a signed-out app hosts no session and sends no request. The attribution
  rule's version stays: no ledger held such an event before, its reader having skipped the kind, so no assignment
  already made changes, and a new event has what follows it derived again as any new point does. Revisit should a
  response that is not the CLI's be measured inside such a stretch.
- Both new keys are written only as false, and an absent one is read as before, as `syncFollows` is.
- The plugin's panel says "at its sign-in page", the window's words, rather than "unknown".
- A sign-in mark the sync cannot read leaves the CLI following `lastKnownAccountUuid`, as before the app had the mark;
  the desktop modes still refuse such a layout. Revisit should a version of the app without the mark be measured.
- The modes write `desktop_signed_out` only on the app's own word — an add's signed-out line, a switch's refusal (exit
  5) — never on an add left unconfirmed or ended in an error: an event the app's word does not back could name the app
  signed out while it is not, with no change the watcher could see to correct it.
- A switch to the account the app is already signed in to writes `desktop_account`, which corrects WindowTally left
  showing the app at its sign-in page after a sign-in the watcher did not see (*Caveats*).
- A watcher look that cannot read `config.json` keeps the desktop half of the view it published, rather than publishing
  no desktop account and writing the event again at the next look; a signed-in view flapped the same way before.

The maintainer's decisions on the desktop band's look (2026-10-26), made over samples of the band drawn in the desktop
app, built the same day:

- The account the session uses stands apart, and its 5-hour window reads first (its weekly window, for an account with
  no 5-hour limit, since 2026-10-31, below). Unfolded, the band is two columns. The
  left holds the fold button over Details. The fold button's label puts the triangle after the word, `Accounts ▾`
  (`Accounts ▸` folded), so that `D` stands under `A` and no second button's spacing is paid. Details stays on the
  second line however many lines the band takes, and loses its button chrome: plain like the fold button, at full
  strength where the fold button is dim, with the app's own grey under the pointer. The right column holds the account
  in use on a line of its own over the other accounts.
- The account in use: an orange `● `, its name semibold with its tags and any renewal tag, then the 5-hour window —
  its figure the band's largest text, bold, with a small meter beside it and its countdown semibold — then the weekly
  window in smaller text, with a smaller meter and a dim countdown. No frame and no tinted background: the line of its
  own, the dot, the size and the meters set it apart. The warning and error colours stand on both windows' figures as
  before, the weekly one's at its smaller size.
- The other accounts: their line opens with a grey `● `, the same glyph at the same size as the in-use dot, so the
  first name stands under the in-use name; they keep the compact words and the `│ ` between them, in smaller dim text.
- Nothing on the band runs past its width: the in-use line's groups (name, 5-hour, weekly) and the other accounts'
  units wrap as wholes, and one wider than the room by itself wraps within itself. For the desktop band this replaces
  the rule that an account is a unit that never splits.
- Folded, the band is as it is: the fold button and the fault flags, and the card of every account under the pointer.
  The maintainer's decision of 2026-10-31 on the folded desktop band (below) puts the accounts between the button and
  the flags.

The maintainer's decisions on the order of the accounts (2026-10-26), built the same day:

- One order of the accounts across WindowTally, set by the user and kept in its settings: the window's cards, its
  Accounts menu, the tray's menus and tooltip, the band, the folded band's card and the panel follow it. status.json
  writes its accounts in that order, where it had sorted them by name, with no key added and no change of version; the
  plugin already kept the order the service gives.
- The account in use always stands first, the rest in the user's order; where the desktop app and the CLI use
  different accounts, both stand first, the app's before the CLI's. A switch therefore moves the cards. Since
  2026-11-04 the accounts whose plan has ended stand after the rest (below).
- The order is set in a small window the Accounts menu opens, *Arrange accounts…*: the accounts in a list, buttons that
  move the selected one up or down, and one that returns to the default order, by name.

Choices made in designing them (2026-10-26):

- The account the band marks as in use is the one the session's use is booked to, as the limit warnings judge it: the
  app's account in a session the desktop app hosts, the CLI's otherwise. Where there is none (the app at its sign-in
  page), the other accounts' line stands alone.
- The fault flags follow the weekly window on the in-use line, as groups that wrap as wholes, so that the in-use name
  keeps its place over the others' names. Revisit should they be found lost there.
- The terminal band keeps its one line and its full words: the terminal draws one size, so the account in use is set
  apart there by weight and colour alone.
- On the band a name longer than 16 characters is cut there with an ellipsis; the window's cards and the panel show it
  whole. Revisit should account names often run past 16. Since the same day a name of the user's own, at most 16
  characters, is never cut (below).
- The history page and the History window keep the accounts in the order they were first seen, which their colours
  follow; the page's account cards, which follow the standings, aside (below).

The maintainer's decision on a name of the user's own for each account (2026-10-26), built with the order the same day
(*The maintainer's decisions in building the one order*, below):

- A name of the user's own for each account, for showing only: set beside the order in *Arrange accounts…*, kept in
  WindowTally's settings, carried as status.json's `label` so every surface shows it, at most 16 characters so the
  band never cuts it, unique, and cleared back to the e-mail's local part; the window's cards and the panel still show
  the e-mail, and every action keeps naming the account by its UUID.

Measured on the development machine in drawing those samples in the desktop app, whose Claude Code was 2.1.299
(2026-10-26):

- A Button is drawn from its own `label`, `plain` and `dimColor` alone: Text children given to it are not drawn, so a
  button's label can be neither bold nor led by a hidden glyph.
- A Text's colour `transparent` is not honoured: the text is drawn in the ordinary colour. An empty SVG given the in-use
  dot's size did not hold its place: the line it opened started short of the in-use name.
- The app keeps space around every button, so two plain buttons side by side stand well apart: a fold glyph in a
  button of its own beside `Accounts` cost about a word's width.
- A Text's `size` and `weight`, raw colours, and SVG drawings sized in pixels are drawn on the band as given.

Choices made in building the band (2026-10-26):

- The cut at 16 characters holds on every band surface — the terminal's line and the folded band's card as well as the
  desktop's lines — since the decision names the band unqualified and only the window's cards and the panel as showing
  a name whole. Revisit should the terminal or the card be wanted to show names whole.
- A character is counted as a reader counts one, a grapheme cluster (`Intl.Segmenter`), so no cut splits an accent from
  its letter or an emoji sequence; code points stand in where the engine has no segmenter, which both Claude Code
  builds have (2.1.310 and 2.1.299, measured by the plugin's tests on 2026-10-26).
- On the terminal the account in use comes first on the line, its name semibold in the theme's `claude` colour, and
  the other accounts are dim with their names at plain weight, the warning and error colours kept on every figure: set
  apart by weight and colour alone, as the desktop's other accounts are dim. Revisit should the terminal line prove
  unclear.
- The meters are filled with WindowTally's status fills (`windowtally/palette.py`), chosen by the window's warning
  figures, over a grey track at 35 % opacity: one set of status colours across WindowTally's surfaces, and a track that
  shows on a light background and a dark one, since a drawing takes raw colours and the plugin cannot read the app's
  theme; the samples' colours were a sample's. Revisit should the track prove too bright or too faint.
- A window not started shows a dim `–` over an empty meter, as the window's cards draw one empty and the tray an empty
  ring; a window with no figure (running, unknown) shows its word and its countdown and no meter, since an empty meter
  would read as a figure nobody read. Revisit should either prove unclear.
- With no account in use the fault flags stand on a line of their own where the in-use line would be, above the
  others' line, which keeps its dot under where the in-use name would stand. Revisit should it be found odd.
- Where the session's surfaces cannot be read, the band takes the surface drawing it for the answer, a desktop band
  being drawn only in a session the app hosts, and logs the failure to the debug log, rather than setting the CLI's
  account apart on the desktop.
- The renewal tag on the in-use line keeps the body size while the other tags are smaller, as the approved samples drew
  it: a renewal is a warning meant to be seen.
- For the unfolded desktop band this replaces the choices of 2026-10-22 and 2026-10-23 that put the tag, `▾ Accounts`,
  at the band's start with the fault flags as units after it, Details at the right end of the first line, and a single
  unit wider than the room left to the desktop app; folded, the band kept the layout they gave it, its button's label
  aside, until the maintainer's decision of 2026-10-31 on the folded desktop band (below).

The maintainer's decisions on a desktop login stored before the app had saved its sign-in (2026-10-26), built the same
day:

- No desktop mode stores a login the app may not yet have written to its Cookies file; how the sync makes sure is
  measured first, from what can be read without any login's value.
- The note of exit 5, and the window's words for it, say which of the two refusals it was, from the restarted app's
  start-up state.
- Whether the window runs a pass after exit 5 is left to the building, with its ground (below).

The maintainer's decision in building them (2026-10-26):

- The notes the window reads grow by a third marker: while a desktop mode waits for the app to save a sign-in just
  made, the sync writes `Waiting for the desktop app to save its sign-in of HH:MM:SS before closing it...`, which the
  window reads (`sync_model.SAVING`) so its header says "… The desktop app is saving its sign-in first; this can still be
  called off." The window is the only reader of these markers; a window older than the script shows its generic
  progress words.
  The modes, the exit codes, `events.jsonl`, `watch.json` and status.json are unchanged: exit 5 keeps its meaning, and
  both refusals write the same `desktop_signed_out` event and set the login aside.

Choices made in building them (2026-10-26):

- Every desktop mode waits before it closes a running app, for a sign-in made in the last 35 seconds, until the
  Cookies file has been written since or the 35 seconds are up (*Rules*, *A sign-in saved before a close*). The ground
  is measured (*Sources*): the cookie store writes a change to the file within 30 seconds, the rest of a sign-in comes
  before its log line, the log stamps to the second, and 5 seconds are a margin. Its cost is a wait of up to 35 seconds
  for a switch, an add or a store asked within 35 seconds of a sign-in. Revisit should a login stored 35 seconds or
  more after its sign-in be refused with `sign_in_cookie_present: false`, or should the app stop writing its sign-in
  line, which leaves no wait and the hazard back, the refusal then at least naming its cause (*Caveats*).
- Not taken: picking the sign-in cookie out of the Cookies file to see whether it is there, which needs an SQLite engine
  in the sync and the cookie's name, unmeasured — the ground on which an add removes the whole file; and having the
  app quit itself, which would run its cleanup, for which no way to ask it from outside was measured.
- The note of exit 5 names its cause from the start-up state's `sign_in_cookie_present` and, where no state was read,
  names none; the exit code, the event and the login set aside stay one for both, since either login is of no further
  use. The window shows the script's last note, so its words follow the note's. Revisit should a version of the app
  stop writing the flag: the note then names no cause.
- The window runs a pass after exit 5, the script's words kept at the head of the status line in the warning colour
  through the pass and its result, as every change followed by a pass now keeps its words ahead of the pass's in the
  warning colour where either did not go as asked. The pass shows the app at its sign-in page and the login set aside
  on the card at once, rather than at the service's next pass. It does not bring a later sign-in in the app to the
  header any sooner: that still waits for the watcher's next look (15 seconds) and the service's next pass (60).
  Revisit should a pass after exit 5 be found to fail often: its failure then follows the refusal's words in the same
  colour. This replaces the choice of 2026-10-25 to run no pass after exit 5, whose own revisit — the window learning
  to keep a warning's colour through a pass — it meets.

The maintainer's decisions in building the one order (2026-10-26):

- The tray's switch menus follow the one order, as every other list does: the account WindowTally recommends keeps
  its `(use next)` mark where it stands and is no longer listed first. This replaces the layout of 2026-10-24, decided
  that day and restated among the choices made in building it, under which the tray menu mirrors the Accounts menu
  with the recommended account listed first.
- The user's own names for the accounts are built with the order, as decided the same day (above): for showing only,
  set beside the order in *Arrange accounts…*, kept in WindowTally's settings, carried as status.json's `label`, at
  most 16 characters so that the band never cuts one, unique, and cleared back to the e-mail's local part; the
  window's cards and the panel still show the e-mail, and every action names the account by its UUID. This meets the
  revisit of the choice that the band cuts a name past 16 characters: a name the user gives is never cut, one taken
  from an e-mail still is.
- settings.json keeps version 1 for its two new keys, as it did for `silenceNotifications` (2026-10-22).

Choices made in designing it (2026-10-26):

- The order is status.json's account list and what reads it: the window's cards, menus and tooltip, the plugin and the
  `status` command. The standings keep their sort by name, now the name shown, which the recommendation's tie-break
  follows, and the history page's account cards stay in it; the history page and the History window are otherwise
  unchanged. Revisit should those cards be wanted in the user's order.
- Accounts the user's order does not list follow the listed ones, by name; a listed UUID no account has is passed
  over, and dropped at the next save of the arrangement.
- By name is by the name shown, a name of the user's own included: case aside, then the name itself, then the UUID,
  so the order is total, two e-mails' local parts being able to match (the UUID added on 2026-10-27, when two accounts
  shown by one name were found to fall back to the order by name whatever order was set between them).
- The history's colours break a tie in first-seen order by the name an account's e-mail gives it, never by the user's
  name, so a rename never moves a colour.
- *Arrange accounts…* lists every account in the user's order, without the accounts in use pulled first, with Up,
  Down, By name, a name field (clearing it restores the default), OK and Cancel; OK writes through WindowTally's
  settings and runs a pass whose words stay at the head of the status line; Escape is Cancel. Revisit should each
  move be wanted applied at once.
- The plugin needs no code for the order: the band keeps the service's order, the accounts in use first. Its types say
  the order, that `label` is the name shown and that `uuid` names the account in every action; the band holds no name
  limit of its own, cutting at 16 grapheme clusters as before.
- The user's name is kept beside the name the e-mail gives, and applied wherever accounts are read for showing — in a
  pass, before the standings, and in the History window's computation — never stored in the ledger. A name holds at
  most 16 code points; control and format characters, spaces before or after, an empty name and a name repeated in the
  file, case aside, are refused. The window also refuses a name another account is already shown by.

Choices made in building it (2026-10-26):

- The tray menu carries *Arrange accounts…* too, after *Add an account…*: it holds what the Accounts menu holds, and
  the window opens from the tray as the switch dialogs do. Revisit should it be wanted in the Accounts menu only.
- The order is written as none while the window's order is the order by name, so that an account added later takes its
  place by name: *the default order, by name* names a rule, not a list. Revisit should a press of *By name* be wanted
  to freeze the list.
- `python -m windowtally bills` names the accounts by the user's names too, as every surface does. Revisit should the
  command line be wanted to name them by their e-mails.
- In the window the spaces typed around a name are dropped, while the file still refuses them: a space typed at a
  name's end is not a choice of name. Revisit should it be found surprising.
- A name typed as the account's default is no name, so no key is written that changes nothing.
- The characters refused are those of the Unicode categories Cc, Cf, Cs, Zl and Zp, which show as nothing or break the
  line a name stands on. An emoji sequence joined by U+200D, a format character, is therefore refused. Revisit should
  emoji sequences be wanted in names.
- While the name typed cannot be used, OK is disabled, the reason stands under the field and the selection stays on
  that account, a bell answering an attempt to move it. Revisit should it be found awkward.
- OK with nothing changed writes nothing and runs no pass.
- The window does not open over settings it cannot read, and the status line says why: an arrangement written over
  them would replace what was not read.
- The window compares a name with every other account's shown name, the defaults included; clearing a name is never
  refused, even where the default then matches another shown name, since two defaults can match already.
- Setting or clearing a name does not re-sort the list; OK writes what the window shows, an explicit order unless it is
  the order by name.
- A pass reads the bills, and the settings they carry, right after attribution and before the accounts in use, so that
  the names are in every standing; settings that cannot be read name and order nothing, as they silence nothing, the
  problem named among the source problems.
- An account's UUID in the order or the names is the canonical 8-4-4-4-12 hexadecimal form, in either case, kept in
  lower case as the registry keys it.

The maintainer's decisions on the account sync's robustness (2026-10-26):

- When the desktop app has agreed to close and its processes outlive the wait, the switch waits on, for about two
  minutes, and finishes, starting the app; past that it refuses in words saying the app was told to close and may be
  partly closed, and exit 2 is then a refusal with no login changed. This replaces the choice of 2026-10-25 that kept
  the refusal after a timed-out close saying nothing was changed.
- A switch that finds the app not running starts it, and reads its log as it does for an app it closed. This replaces
  the choice of 2026-10-25 that an app that was not running is not started, and with it the contrast the add's choice
  of 2026-10-26 drew: a switch and an add both start the app now.
- WindowTally is to show that the desktop app is not running and offer to start it. It was not built with these,
  needing a fact the watcher publishes, carried through status.json; it is built since 2026-10-27 (below).
- A CLI that has signed itself out is reported only where the CLI follows the app: the condition keeps its meaning,
  what keeps the CLI from following, and while following is off or the app is at its sign-in page WindowTally says
  nothing of it.

Measured on the development machine in building them (2026-10-26):

- The desktop app's own Claude Code writes the `oauthAccount` label of the account the app signs in to in
  `~/.claude.json`, four seconds after a sign-in in the app, and leaves the CLI's sign-in file as it was; the sync
  refused that label at once. A CLI later started by its path, not through the launcher, refreshed its token,
  rewriting the sign-in file alone. Under the rule then in force a changed sign-in file was enough to trust the label,
  so trust moved to the label's account, and the watcher's next store, once no CLI ran, filed the tokens of the
  account the file held under the label's account.
- A CLI whose sign-in could no longer be refreshed rewrote its sign-in file at about half its size and reported itself
  signed out; only the size was seen, never the content. The label had not changed, so the sync stored that file over
  the account's last good copy, and nothing was shown.
- Reading each process's own path, which walks its module list, took many times as long over the development
  machine's processes outside session 0 as one CIM query of every process's image path. A close's wait read the paths
  that way, so a listing begun right after the end was announced was itself slow, which very likely explained the
  refusals seen after a timed-out close: a reading of the measurement, not a certainty. With the wait at
  30 seconds the app's processes were still listed 38 seconds after the app logged its quit, and none 85 seconds after.

Choices made in building them (2026-10-26):

- A label naming another account than the trusted one is placed by when the sign-in file was written against the span
  in which the label appeared, within 30 seconds of it (*Rules*, *The CLI's sign-in*): a sign-in writes both within
  seconds, while a refresh or a sign-out writes the file alone and the app's Claude Code the label alone. Not taken: a
  refusal that holds across later writes of the file, which would strand the CLI after every sign-in in the app; taking
  every write after a foreign label for a refresh, which would misfile a sign-in the sync did not see; trusting only a
  label and file changed between the same two looks, which a look between a sign-in's two writes, file first, would
  turn into the new account's tokens filed under the old; and reading the token's account, which the file does not name
  and the server would have to be asked for, which WindowTally's passivity rules out. Its cost is the accepted window
  (*Caveats*). Revisit should a sign-in be measured to write its two halves more than 30 seconds apart, or the app's
  label write to coincide with refreshes.
- While the sign-in file is the one the trusted label was last seen with, the sync acts for the trusted account: it
  stores the file as that account's, its own profile kept, and follows the app or puts the account's label back. The
  file is certainly that account's, and without this the CLI would stop following after every sign-in in the app whose
  label the app's Claude Code writes before the watcher looks.
- Once the file has been rewritten under a foreign label, nothing is stored or switched until the label returns or a
  sign-in through the launcher settles it: whose tokens they are cannot be told, and a refusal that shows beats a
  silent misfiling. Revisit should a way be found to tell a token's account on the machine alone.
- The launcher witnesses a sign-in: `claude.cmd` passes `-SignedIn` after a `claude auth login` that ended 0, and the
  sync still asks the file to have been written within the window. The launcher is the one party that sees a sign-in
  happen. Revisit should `claude auth login` be measured to end 0 without signing in.
- A `state.json` from before looks were recorded places no foreign label on a changed file: with no look to bound the
  span, a refresh looks like a sign-in.
- A sign-in file holds a sign-in only where both OAuth tokens are non-empty strings: the signed-out file was seen by its
  size alone, and any file without the pair holds nothing to store. Revisit should a signed-out file be measured to
  keep both tokens.
- A CLI signed out of the desktop app's account is not put back on that account's stored copy, which is the copy
  whose refresh failed or an older link of it, so a restore would fail at every CLI run; the copy is not set aside, the
  store gaining no state for it. `SwitchCli` to that account ends 3, which the window answers with a terminal for
  `claude auth login`. Revisit should such a stored copy be measured to be still good after a sign-out.
- `watch.json`'s `cliAccount` keeps naming the label's account for a signed-out CLI: the service falls back to the last
  CLI event where it is null, so WindowTally would show the same, and no key changes.
- The close waits up to 120 seconds until no process of the app is left, and only a listing begun once the time is up
  refuses. A process that was not among those asked is not refused on sight, since the app may start a short-lived one
  as it quits; still there at the end of the wait, it names the refusal. Revisit should the app's processes be measured
  never to exit, when a shorter bound and other words would serve.
- The app's processes are listed through one CIM query, a process's own path read only for an object that is not a
  live process and for every process when the query fails. The branch on the object's type keeps the listing testable
  against a made-up list; keying on whether the query holds an id instead could match a made-up id to a real process.
  Revisit should a CIM image path be measured to differ from a process's own path for an app process.
- A switch starts the app whether or not it was running; a switch that fails starts only an app it closed, since a
  failure should not open an app the user had closed; a switch to the account the app is already signed in to starts
  nothing.

The maintainer's decision on the Details panel's look (2026-10-27), built the same day:

- The panel takes the band's look, and what it says twice is said once.

Choices made in designing it (2026-10-27):

- Each account is a block opened by the band's dot, orange for the account the session's use is booked to, as the band
  marks it, grey for the others, then the account's name, semibold, and its tags in the panel's full words (`desktop
  app`, `CLI`, `use next`); after them, smaller and dim, its e-mail where the name is not it, the age of its last
  response and the age of the reading its figures rest on.
- Every block draws its windows at the scale of the band's in-use line: the 5-hour figure the panel's largest text,
  bold, beside the band's meter and a semibold countdown; the weekly figure smaller, beside the smaller meter and a dim
  countdown; the warning and error colours on both figures, as on the band. The other accounts are not dimmed as they
  are on the band: the panel is where every account's figures are read, and the dot already sets the account in use
  apart. Revisit should the others be wanted subdued as on the band.
- The words stay whole, as the maintainer's decision of 2026-10-23 keeps them in the panel: each window is named
  (`5-hour`, `Weekly`), a window not started says `not started`, without the gloss on what opens one that the panel
  had written, and a window with no figure says `running` or `unknown`, where the band writes `5h`, `week` and a dash;
  the 5-hour window of an account with no 5-hour limit says `no limit`, the band's compact words `none` (since
  2026-10-31, below; since 2026-11-14 the band shows no 5-hour window for such an account, below). The window names
  take one width, so the figures of every block stand in one column.
- Beside a countdown, smaller and dim, stand what the band does not carry: the wall-clock reset time, marked ≈ where
  it was inferred, the countdown standing for the `(in …)` the panel wrote after it; the time at which the pace runs
  out, where there is one; and, beside a weekly reset time, whether it was read or inferred, as the maintainer's
  decision of 2026-10-21 has it.
- A reading's age is said once per block, with the e-mail, where both windows rest on the same observation, and beside
  each window only where they differ, where every window line had repeated it.
- The plan line stays under the windows, smaller and dim, its warnings in the warning colour; the renewal stays there
  alone, not repeated as a tag beside the name.
- The head holds the window button, the recommendation (`Next:` and its reason, with when the first account opens or
  room returns) and only what the blocks cannot say: that the service may not be running; the desktop app at its
  sign-in page, or an account the app or the CLI uses that WindowTally does not list; and the CLI's condition (since
  2026-10-27 also a desktop app that is not running, below). The line naming both clients'
  accounts is dropped where the blocks' tags already name them, and the time the status was written moves to the foot,
  smaller and dim.
- The foot holds the source problems as before, the status time, and one line for the panel's own marks, `≈ marks a
  figure or time inferred rather than read; ↻ is the time until a window resets.`, in place of the line that described
  the band's ↻.
- Nothing runs past the pane's width: a line's groups wrap as wholes, a further line starting under the line's own
  content, never at the pane's left edge, where the panel's lines had wrapped to.
- Where the surface drawing the panel carries no sizes or drawings, the account in use is set apart by weight and
  colour alone and no meter is drawn, as on the terminal band. Which surfaces draw the pane, and whether a pane's site
  draws a Text's size and a drawing as the band's site does, were left to be measured in building it (below), the
  band's having been measured on its own site (2026-10-26).

Measured on the development machine in building it (2026-10-27):

- The desktop app, 2.42304.0.0, forwards every render the plugin answers, the pane's and the band's alike, under its
  one surface, `desktop` (its bundle, `app.asar`); the CLI raises it on the terminal. Claude Code's hook API, 2.1.299,
  names the surface a pane is drawn on and gives the desktop's, the mobile app's and the editor's surfaces an element
  table that carries a drawing, the terminal's one that carries none and draws one size.
  Whether the app paints a pane's sizes and drawings as it paints the band's lies in its renderer, not in the bundle,
  and is seen by eye (*Caveats*).

Choices made in building it (2026-10-27):

- Sizes and meters are drawn wherever the surface's element table carries a drawing, and on no other surface: the
  panel then draws what each surface can paint, where keying on the terminal alone would hand a drawing to any surface
  added later that has none. Revisit should the pane's site in the desktop app be seen dropping sizes or drawings.
- On the terminal no figure or countdown takes a weight of its own and the weekly countdown stays dim, so that the
  account in use is set apart by its name, semibold in the `claude` colour, and its orange dot alone, as on the
  terminal band, and the weekly window keeps the one mark the terminal leaves it. Revisit should the figures be wanted
  bold there.
- The rows' names take one width through the monospaced face and padding with no-break spaces, rather than through a
  box's width, whose unit on a graphical surface Claude Code does not document. Revisit should the figures be seen out
  of line.
- The head's line naming both clients' accounts is dropped whole: the app is named there only at its sign-in page or
  on an account WindowTally does not list, the CLI only on an account WindowTally does not list, and an account not
  known is not said; the CLI's condition takes the window's words.

The maintainer's decisions on WindowTally's word on a desktop app that is not running (2026-10-27), built the same
day:

- The contract grows without a change of version: `watch.json` and status.json each gain `desktopRunning`, written
  only as false, while the desktop app is not running, an absent key meaning running or not known, as `desktopSignedIn`
  was added on 2026-10-26. The account sync gains a mode, `StartDesktop`, which the window runs to start the app: it
  ends 0 when it started the app, or found it running and started nothing, 2 when it refuses because another of the
  sync's acts is in progress, and 1 on an error. The service, the window, the plugin and the `status` command read the
  key.
- The window's header reads `Desktop app: <account> (not running)`, and under the header a line, `The desktop app is
  not running.`, stands with a button, `Start the desktop app`; while the app starts, the progress row says `Starting
  the desktop app…` and cannot be cancelled; the cards' switch buttons are unchanged. The tray menu gains `Start the
  desktop app`, enabled only while the app is reported not running, and the tooltip's first line reads `Desktop app
  not running`; the tray icon is unchanged and no notification is raised. On the terminal band that account's `app`
  tag reads `app closed`. The panel's head says `The desktop app is not running; start it from
  the WindowTally window.`, and that account's tag reads `desktop app, not running`. The plugin does not start the app
  itself. Not taken: a start button in the panel, which would widen the plugin to run the sync, and a start in the
  tray alone, with nothing in the window's header.

Measured on the development machine in building it (2026-10-27):

- Listing the desktop app's processes the way a switch lists them takes about half a second, the median of eight runs
  against an app folder holding no process. The watcher lists them once every 15 seconds.

Choices made in building it (2026-10-27):

- The watcher reads whether the app runs only in a look that holds the act mutex, and a look that finds it held by
  another act leaves the published view whole — the condition, the accounts and the running state alike. An act closes
  and starts the app and changes the logins and the CLI itself, and records its changes as events; a view read during
  it would be newer than those events and wrong, such as an app read not running just after a switch started it. This
  also ends the condition being cleared and logged again around every act. Revisit should a reading during an act be
  needed.
- While the app is not running the watcher writes its view at every look. A view's time otherwise marks only its last
  change, so an event written while the app stayed closed would clear `not running` for good: a switch to the account
  the app is already signed in to writes an event and starts nothing. Its cost is one write of some 150 bytes every
  15 seconds while the app is closed. Revisit should that write be measured to cost something.
- The service takes `not running` only from a view no older than two minutes (`NOT_RUNNING_FRESH`). Given the rewrite
  at every look, an older view means the watcher stopped, and the app may have been started by hand since; this leaves
  no case in which WindowTally goes on saying `not running` of an app started by hand while the watcher is stopped.
  Revisit should the watcher's interval be made longer than about a minute.
- `StartDesktop` records the app's account, or its sign-in page, as a switch records it, the event kinds and their
  meaning unchanged. Without it the plugin and the `status` command would go on saying `not running` for up to about
  75 seconds after a start (the watcher's 15 seconds and the service's minute), where the window's own pass right after
  the start now clears it for every surface. Revisit should the event be measured to disturb attribution.
- A session the desktop app hosts never reads the app not running: it runs inside the app, so the word can only be
  stale there. Revisit should every surface be wanted to show status.json as it stands.
- While the window's own start stands, the header's ` (not running)`, the line under it and the tray's start are
  withheld and the progress row says `Starting the desktop app…`, as the window keeps a switch's state until a status
  confirms it; the start ends at a status saying the app runs, at one written 20 seconds or more after the start saying
  it does not (the watcher's 15 seconds and a margin), or after five minutes, so a stopped service cannot hold it.
  Revisit should the header be wanted to keep `(not running)` during a start.
- A start asked for from the tray with the window hidden raises a notification only where it was not done: the
  decision raises none for the not-running state, and a start that worked is answered by the app's own window.
  Revisit should a start that worked be wanted notified as a switch is.
- The `status` command gives the app's account the role `desktop, not running`, and adds a line `Desktop app: not
  running` only where no account `isDesktop`. The decision named the command a reader without giving it words.
- The watcher lists every process each look rather than a cheaper listing, since the app is told by its folder, never
  by a process name (*Measured*, above). Revisit should a cheaper listing that still keys on the folder be found.
- A job's end carries its kind beside its outcome, compared by neither, so that the window can route a start's end
  while every end is still compared by what it came to.

The maintainer's decisions on chat on claude.ai in a browser (2026-10-27), built on 2026-10-29 (below):

- WindowTally stays passive (2026-10-20, above), the decision's ground examined again. As read that day: Anthropic's
  Consumer Terms (https://www.anthropic.com/legal/consumer-terms, effective 2025-10-08) forbid, in section 3, reaching
  the Services by automated or non-human means, a bot or a script, other than with an Anthropic API key or where
  Anthropic explicitly permits it, and let Anthropic, in section 12, suspend or end access without notice where it
  believes them materially breached; Claude Code's Legal and compliance page
  (https://code.claude.com/docs/en/legal-and-compliance) says a subscription's OAuth sign-in is designed for ordinary
  use of Claude Code and Anthropic's other native applications, that developers may not collect, store or
  intermediate Claude.ai credentials or session tokens, and that Anthropic may enforce this without prior notice. The
  enforcement reported through 2026, in secondary sources only, refused other clients' requests made with a
  subscription's sign-in; no primary source confirmed an account closed for it, and none was found closed for reading
  its own usage, through an endpoint no Anthropic documentation was found to describe and which reports from March
  2026 show refusing a polling client for hours at a time, Claude Code's own `/usage` with it. A fetch of an idle
  account's figures would also have to refresh its stored sign-in, whose refresh token rotates on use (the account
  sync's own description): the service would become a writer of credentials, against *Parts and processes*, and a
  write lost or raced would leave that account's stored sign-in spent, and the CLI would have to be signed in to it
  again with `claude auth login`.
- Chat on claude.ai in a browser on this machine is to reach WindowTally through a Chrome extension that reads the
  5-hour and weekly figures claude.ai's own page receives and hands them to WindowTally: it makes no request of its own
  and reads no credential, so the decision above stands. The extension is optional, and offered as such: WindowTally
  stands whole without it.

The maintainer's decision on a bill's amount (2026-10-27):

- A bill goes on recording the amount it was charged and its currency, though no figure uses them. This answers the
  question left open on 2026-10-23 (above); it leaves nothing open, and nothing in the bills file or the bill form
  changes.

The maintainer's decision on the measure of what a plan's limits hold (2026-10-27):

- The measure of what a plan's limits hold is stated per plan, from that plan's own readings on this machine, in
  absolute terms, and never derived from the marketed multiples between plans; a plan with no readings here shows no
  figure until someone uses it here. This settles what the measure states, not how it is measured, which was left to a
  study of the readings. Since 2026-10-28 the measure is built without that study (below).

The maintainer's decision on the names of accounts the arrangement does not list (2026-10-27), built the same day:

- *Arrange accounts…* keeps the names the settings hold for accounts it does not list, rather than dropping them at the
  next save: a dropped name is lost without a word, while a name kept is refused where the user types an equal one.
  Since the ledger never removes an account and status.json lists every account it knows, such a name is one for an
  account that appeared since the service's last pass, or one written by hand for a UUID no account here has. The
  consequence accepted: such a name blocks an equal name, case aside, and only removing it from settings.json frees it.
  The order half of the same write stands as decided (*Rules*, *One order, one name*): a UUID in the order that no
  listed account has is still dropped at the next save.

The maintainer's decision in building it (2026-10-27), since the ground above did not hold as the window stood: the
window refused a name only by the accounts it lists, so a name equal to a kept one would have been refused only by the
settings file after OK, naming both accounts by UUID alone, and the window, knowing nothing of such an account but its
UUID, has no way to clear its name:

- The name field refuses a name equal to one the settings keep for an account the window does not list, as it is typed,
  naming that account by its UUID and saying that removing the name from settings.json frees it. Not taken: listing
  those accounts in the window, below the others and outside the order, so their names could be cleared there; or going
  on dropping the names. Revisit, towards the listing, should WindowTally ever remove an account from its list.

Choices made in building it (2026-10-27):

- The kept names are written after the listed accounts' in `accountNames`: the object's key order means nothing to any
  reader, and listed first keeps the file reading like the window. Revisit should a reader be found to depend on it.
- The arrangement keeps only the names of UUIDs its rows do not list, whatever names it is handed, so a listed
  account's name is always its row's.

Choices made in keeping an edit of the settings made while *Arrange accounts…* is open (2026-10-28). The window had
read the order and the names once, at open, and OK wrote both back whole, so a change made to them meanwhile was undone
without a word. Such a change can only be made by hand: one window runs per user (`instance_model`, the window lock),
and no other part of WindowTally writes the two keys — every other settings writer (the bill sources, the renewal
reminder, the silencing of notifications) writes keys of its own, keeping these as it reads them under the same edit
lock.

- OK lays what the window changed onto the settings as they stand at OK, read under the file's edit lock: against the
  order and names read when the window opened, what the window changed is written as the window has it, and what it
  left alone as the settings hold it then. Not taken: refusing OK on any change made meanwhile, which would throw away
  the user's edits even where the hand edit touched nothing the window changed; reloading the window whenever the file
  changes. Revisit, towards the reload, should a writer appear that changes these keys often while the window is open.
- The order is one thing, not merged position by position, since two orders edited apart cannot be interleaved with any
  meaning; two orders are one where they put the listed accounts alike, however written. An order set by hand while the
  window left the order alone is written as the settings hold it, less the UUIDs no listed account has, which every
  save of the arrangement drops (*Rules*, *One order, one name*); with no change elsewhere the window writes the order
  it shows, as before. A rename that makes the list stop being the order by name counts as the window changing the
  order, since OK writes what the window shows. Revisit should hand-set UUIDs be wanted kept, or the order merged by
  position.
- Where the window and the settings both changed the order, or one listed account's name, each to a different value,
  nothing is written, and the window's problem line names what settings.json changed since it opened — the order, or
  an account's name by its e-mail with what it is now — and says that OK again saves the window's over those changes
  and Cancel keeps them. What was said counts as told: OK again writes the window's value over exactly that, unless the
  settings changed it once more, which is said again. A change made by hand equal to the window's own is no conflict.
  Only a save counts as telling the user. Revisit should a conflict be wanted to end only in Cancel and reopening.
- A name the window gives that the settings, as they stand at OK, meanwhile gave another account — listed, kept for an
  account the window does not list, or freed as a listed account's default by clearing its name by hand — is refused,
  case aside, nothing written, the message naming that account by its e-mail, or by its UUID where the window does not
  list it, and asking for another name; OK again repeats the refusal until the name changes, since that other name is
  not the window's edit to save over. A name the window clears is never refused, as where it is typed (2026-10-26).
  The name field still checks a name as typed against the names read at open, so after such a change it may accept a
  name that OK then refuses; the refusal is said and nothing is lost.
- `settings.set_account_arrangement` keeps its signature and replaces what the file holds of the two keys; a writer
  that shows the user what it read, as the window does, writes through `settings.edit_account_arrangement`, which hands
  the settings read under the lock to the writer's own edit, since only the window knows what it changed.

The maintainer's decisions on the measure of what a plan's limits hold (2026-10-28), built the same day:

- The measure is built without the study of the readings, and this decision replaces the condition of 2026-10-27
  (above) that its method wait on that study. It can only be counted as though all of an account's use were Claude
  Code, so each surface that shows it says so, for the user to know; everything else is computed directly in
  API-equivalent dollars, WindowTally's own unit.
- What it states stands as decided on 2026-10-27 (above): per plan, from that plan's own readings on this machine, in
  absolute terms, never derived from the marketed multiples between plans, a plan with no readings here showing no
  figure until it is used here. For each plan it gives what one full 5-hour window and one full weekly window held,
  and whether that changed from week to week.
- Where it is shown stands as the maintainer decided on 2026-10-23: in the History window and on the history page, not
  in the plugin.

Choices made in building it (2026-10-28):

- The figure is what one full window held: 100 × the dollars over the points the window rose, summed over the steps
  (*Rules*, *What a full window holds*), the decided quantity stated directly.
- A step's readings are at most three hours apart, as for the estimates, since use elsewhere could hide in a longer
  gap; neither is at 99 % or more, where the figure stops rising with use and extra usage would be counted; and the
  figure did not fall at all: inside a window one instrument only reads it higher, so even a fall short of a reset's
  three points is a reset nothing else showed, and counting it as a negative rise would lift the figure above the lower
  bound it is. No reset lies between them by the readings' own reset times, else by the 5-hour window rule the
  standings use (`limits.five_hour_end`, made callable at any reading) or the account's weekly anchor, taken from all
  its weekly readings from a week before the range on, later ones included. Responses of the account were recorded
  between them, every one with a list price, since an unpriced response leaves the step's dollars unknown. Revisit
  should a measurement show a rule losing most of the evidence or biasing the figure. The rule on falls, and the need
  for a response between the readings, were replaced the same day after such a measurement (below).
- One instrument per stretch: an account's plugin readings of a window from the first of them on, its app samples
  before that, and never a step between the two. The two read the figure at different moments and can disagree by a
  point (since the same day measured to disagree because they round it differently, below): pairing them would turn
  that into a steady over-count of points, and using both would count one use twice. Revisit should a measurement
  show the app's samples agreeing with the plugin's readings.
- An account's plan comes from the bills alone: the recorded plan in effect, a plan's periods that run on into each
  other joined, and the UTC day a plan began or changed no plan's, since a bill gives the day of a change and not its
  hour; an account with no bills contributes nothing. The profile names only today's plan, and the History window
  reads no profile. Revisit should accounts without bills be wanted measured by their profile's plan.
- The rounding threshold is derived in code, not a setting. Readings are whole points, so a run of consecutive steps
  rises by its last reading less its first, off by less than a point, and the runs' errors are independent: over n
  runs the rise is off by more than √n points only rarely, √n being about 2.4 standard deviations of such a sum. A
  figure is stated only where that moves it by a tenth or less — a rise of at least ten points per √n — and reads —
  otherwise. Revisit should another precision than a tenth be wanted.
- A plan's accounts count together. Weeks run from local Monday, the grid every other weekly figure on the two
  surfaces uses, and a step falls in the week of its later reading. The per-plan table covers the range — six weeks on
  the page, the chosen span in the window, as every section but the subscriptions does — and the week table has a row
  for each plan in each week with a step. A week is marked higher or lower where its figure reads differently from the
  plan's last stated one and differs from it by more than the two figures' rounding. Revisit should rows by each
  account's own weekly window be wanted.
- The section follows the subscriptions and comes before the hours with every account exhausted, on both surfaces,
  under the headings "What a full window holds, by plan" (on the page with ", last six weeks") and "What a full window
  holds, week by week". The caveat stands under the first heading, before the figures — on the page in the ink of its
  lead lines, in the window as a note — and the method note after the tables. The per-plan table lists every plan a
  bill can name, Pro, Max 5x and Ultra, under Plan, Full 5-hour window, Full weekly window and Held by, the last
  naming the accounts the bills put on the plan in the range, from its periods in effect, their first day included,
  or "none here"; the week table gives Week, Plan and the two windows. Both tables gained a column, 5-hour windows in a
  week, on 2026-10-29 (below): before Held by in the first, last in the second. A sum is in whole dollars from $10
  and in cents below, so the sum shown is never coarser than the tenth it is good to; it carries no ≈, being no
  estimate in WindowTally's sense, and no ≥, since rounding can lift one figure a little and the caveat says "lower
  bound" in words. Revisit should the maintainer want any of it otherwise.
- The measure is a module of its own, `capacity`; its rows and words are the figures layer's (`history`), so the page
  and the window cannot disagree.
- The estimates' points-per-dollar rate (`limits.percent_per_dollar`) is left as it is, since changing it changes
  every ≈ figure, though it counts pairs of readings that measure no rise, which the measure leaves out. Since the
  same day one rule counts both (below).

The maintainer's decisions on the history page in the window (2026-10-28), built the same day:

- The window's History page button, its File menu entry and the tray menu's entry go, the History window showing the
  page's content already; the History window saves what it shows as one HTML file instead. This replaces the decision
  of 2026-10-21 that the window's History page button writes the page afresh and opens it (above).
- The service goes on writing the history page in the background, and the command line's `dashboard` stays; only the
  window's entries go.
- The export is exactly what the History window shows: its chosen span — 7 days, 30 days, 6 months or all — and its
  sections in its order, with no account cards and no recommendation.
- This settles how the window offers the history in a browser; it leaves nothing open.

Choices made in building it (2026-10-28):

- The export writes the history the window shows, as computed for it, with no new computation and no pass, so it is
  at once what the user sees. Revisit should an export fresher than the window be wanted.
- *Export HTML…* stands after Recompute at the History window's head, and Ctrl+S does the same. A save dialog offers
  `windowtally-history-<span>-<day>.html`, first in the user's Downloads folder, else the home folder, then in the
  folder of the last export while the window runs; the folder is not kept across starts. Revisit should it be wanted
  kept.
- The file is opened in the default browser once written, as the History page button opened the page. Revisit should
  that not be wanted.
- The export's HTML is the page's markup (`dashboard.render_history`), in the service's package rather than the
  window's: one HTML layer for the history, and the service's package never depends on the window's. The page's
  sections take the window's span, its words and its per-week columns; a cost chart labels about ten of its columns
  whatever their number, every third over the page's thirty days as before. Its headings carry no period, as the
  window's do, the line under its title naming the span and its first day; its subscriptions are in the window's
  words, which name the window's buttons, and without the profile check, which the window does not read. Revisit
  should the export need something only the window's widgets can show.
- The three entries went together, being one action. Revisit should the File menu entry be wanted back.
- An export that cannot be rendered or written says "Not exported" and why, and one written but not opened says where
  it went and why it was not opened, on the History window's status line. A file another program holds is refused at
  once rather than waited for, since the window's thread would wait meanwhile. Before anything is computed the export
  says the history is still being computed, or that it was not computed, and writes nothing.
- The command line gains no export of a span; `dashboard` writes the page as before.

The maintainer's decisions on how a window's rise is counted (2026-10-28), made on the measurement below and built
the same day:

- One rule counts what the readings say an account's use raised a window by, for both the ≈ estimates' rate and the
  measure of what a full window holds: runs of consecutive readings of one instrument inside one window, each counted
  by how far it rose across the run (*Rules*, *What a full window holds*). This replaces two choices made in building
  the measure (above): that a step's figure did not fall at all, and that the estimates' rate be left as it was. Not
  taken: the rate alone taking on the measure's rule that any fall ends a step; leaving both as they were.
- Inside a run each step counts how far its later reading took the run's highest reading so far, never negative, and
  in the 5-hour window a fall between two readings naming one window end never ends the run. Not taken: each step
  counting its signed rise, a fall of three points or more ending a run in either window; nor this rule with a run
  also ending at a step that has no response between its readings and passes the run's highest so far.
- It does not settle which rounding of a window's figure WindowTally shows, Claude Code's or the desktop app's; since
  2026-10-29 a window's figure is the highest any observation has read (below).

Measured on the development machine (2026-10-28):

- Claude Code's readings fall inside one window, by one to four points in the 5-hour window and by one in the weekly
  one, between consecutive readings naming one reset time, each time between two different sessions' readings seconds
  apart, never within one session. The measure's first rule rested on the opposite, that one instrument does not read
  a figure lower inside a window. The reset time a reading names did not move within a window, and moved by an hour or
  more from one window to the next.
- The desktop app's samples and Claude Code's readings taken within 60 s of each other: the app's often one point
  higher, rarely one point lower, alike otherwise — the two rounding one figure differently, not reading it at
  different moments.
- Every response measured had a list price, so the need for one cut no step. The old rate's pairs across a 5-hour
  window's end, or at the cap, moved it little; its pairs across the two instruments moved the weekly rate markedly,
  and so did the rise back from a trailing reading, counted whole after the fall to it was skipped.
- Against the rules replaced, the rate fell and what a full window held rose, per account and window; a weekly
  figure the rounding bound of its many former chains had left unstated could be stated, the runs it sums being far
  fewer than those chains.

Choices made in building it (2026-10-28):

- The rule is `limits.rises`, beside the rate in `limits`, which `capacity` already reads, so one function gives both
  their steps; `capacity` adds only its test of the plan, through the function's `group`. Revisit should another
  consumer want runs cut otherwise.
- Two readings name one window end where their reset times differ by less than two seconds
  (`limits.SAME_WINDOW_END`): within a window the reset time did not move, and between windows it moved by an hour or
  more. Revisit should a reading's reset time be found to wander within a window.
- In the weekly window a fall of three points or more still ends a run where the reset time holds, since a reset
  granted outside the schedule can leave it as it was; weekly readings were measured trailing by one point only.
  Revisit should one be found trailing by three or more.
- A step with no response between its readings counts inside a run, its points and no dollars, so a run's points and
  dollars stay whole; a run across which nothing was spent here measures nothing WindowTally can price — an idle
  stretch, or use elsewhere — and is left out whole, which also keeps it from widening the measure's rounding bound by
  a chain. Revisit should runs with no spend be wanted for anything.
- A run now rises by its highest reading less its first, still off by less than a point, so the rounding bound
  chosen in building the measure (above) stands. A run's first reading can also be one trailing another session's by
  a few points, which lifts the run's rise by as much; few readings trail, so the bound is left to rounding alone.
  Revisit should the measure's figures be found moving by more than their bound from week to week for this reason.
- Each step stands where it happened, so a cut through a run — the start of the rate's two weeks, a week's edge in the
  history — counts no trailing reading twice. The rate reads each account's responses once per window, from three
  weeks back for the weekly anchor, which costs a pass little: a service pass is its only caller. Revisit should the
  rate be wanted on a path that runs more often.

The maintainer's decision on the History window's layout (2026-10-28), built the same day:

- The History window's summary tiles, charts and tables line up, sharing the scrolling column's two edges, and the
  history page's tiles, and the export's, take the same columns of one width; the page's tables already filled its
  width and its charts already began at one place.
- The summary decided on 2026-10-23 (above) is a row of tiles wrapping where the width ends; the tiles still wrap,
  now in columns of one width on both surfaces.

Choices made in aligning them (2026-10-28):

- The window's tiles stand in columns of one width across the column (`tiles_model`, with no toolkit, as the tables'
  and the charts' layouts are), each stretched to its columns and to its row's tallest tile; a tile too wide for one
  column takes as many side by side as it needs, and the tiles keep their order, one that does not fit what is left of
  a row starting the next. There are as many columns as let the tiles stand in the fewest rows, and of those counts
  the fewest, never more columns than tiles: measured on the development machine at 200 % (2026-10-28), the default
  window holds thirty days' nine tiles in five columns and two rows. Not taken: columns as wide as the median tile,
  under which every tile wider than the median takes two. Revisit should every tile be wanted one column wide, the
  columns then as wide as the widest tile and the rows more. Since 2026-11-02 every tile stands in one column, its
  caption wrapped to it (below).
- The tiles are placed again only when the column's width changes or a tile's words change size, as a change of font
  makes them: every caption and figure reports its size as the tiles first show, and one placing serves them all. The
  placing is not put off until the window is idle, which would let a resize paint the tiles where they were for a
  frame.
- Every table fills the column's width, what its columns do not need shared among them in proportion to their widths,
  as a browser widens the page's tables, which are set to the page's width; a table whose columns need more keeps
  their width and its sideways bar. Revisit should wide, sparse tables read worse, every table then taking the widest
  table's own width instead.
- Every chart's plot starts after the widest value-axis label of all the window's charts, so their axes stand at one
  place and their plots are one width; each began after its own widest label, so the axes stood apart as their labels'
  widths differed. Revisit should one chart's labels grow far wider than the others', the shared space then narrowing
  every chart.
- A chart keeps its right inset of 0.8 of a line, so its gridlines end that much short of the tiles' and tables' right
  edge while its canvas reaches it: a mark or tick label at the span's end would otherwise be cut. Revisit should
  flush gridlines be wanted.
- On the history page and in the window's export, which share one style sheet, the tiles stand in a grid of columns
  at least 160 px wide that share the width, five across the page at its widest, 1000 px; with fewer tiles than
  columns the tiles widen to the edge, as the window never takes more columns than tiles. Each tile is a column with
  its figure at its foot, so a row's figures stand on one line however many lines its captions take.
- On the page a caption too long for its column wraps inside its tile rather than taking two columns, since a style
  sheet cannot measure a caption to find that its tile needs two, as the window does (since 2026-11-02 the window's
  captions wrap so too, below). Measured in Segoe UI at the
  page's sizes (2026-10-28), 160 px holds on one line every caption but *Hours with every account exhausted* and the
  share of the use with no known account, or of an account with a long name; the page's five columns of about 190 px
  hold the share of the use with no known account too. A word that cannot fit its tile, such as a long account name
  with no space, breaks rather than spilling out; a figure with no space stays inside the 126 px of the narrowest
  column up to a cost of seven digits, $1,234,567 being 104 px at the page's 22 px, money from $1,000 up being shown
  in whole dollars. Revisit should the long tile be wanted across two columns, which needs a mark on that tile in the
  markup.

The maintainer's decision on a window's figure (2026-10-29), built the same day:

- A window's figure is the highest any observation of the window now running has read, never merely the latest
  (*Rules*, *A window's figure*). Use only raises a figure inside a window, and both sources give whole points, so a
  lower figure read after a higher one — a Claude Code session's reading trailing another's, or Claude Code's
  rounding of the figure a point below the desktop app's — says less of what the window holds than the one before
  it. Revisit should a window's figure be shown to fall inside a window other than at a reset.
- This settles which rounding a window's figure shows, left open on 2026-10-28 (above): the higher. What the rule
  cannot reach is a consequence of it, not an open question: while Claude Code's readings rise past the desktop app's
  last sample, the figure is Claude Code's rounding again (*Caveats*).

Measured on the development machine (2026-10-29): neither the desktop app's samples nor Claude Code's readings, in
either window, hold a fraction of a point; and no 5-hour reading of Claude Code's named a window that had already ended
when it was taken.

The maintainer's decision on how the browser extension reaches WindowTally (2026-10-29), built the same day:

- The Chrome extension for chat on claude.ai in a browser, decided on 2026-10-27 (above), hands its figures to
  WindowTally through Chrome's native messaging: WindowTally opens no listening port, and installing the extension's
  host registers one key in the user's own part of the registry. The file the extension writes, a contract between two
  parts, was left for the maintainer to confirm, which they did the same day (below).

Choices made in building the rule of a window's figure (2026-10-29):

- An estimate's rise starts at the latest observation, not at the highest reading's time: the latest reading counts
  all use before it, whatever figure it reads, so starting at the highest reading would add again what a later
  reading already covers. Revisit should a reading be found to lag the use it counts by minutes.
- Where no weekly reset time is known, from a reading or the account's anchor, the latest observation stands alone,
  and no projection of when the week fills is made: without the week's start, an earlier week's reading cannot be
  told from this week's. Revisit should accounts the desktop app alone samples gain another source of the week's
  start.
- The standing stays as of the latest observation: the highest reading still holds at that time, use only rising,
  and the estimate starts there.
- An observation taken within a minute of a window's start does not count for it, since it may still read the window
  before; nor does one whose reset time names another window's end, a guard kept though no such 5-hour reading was
  measured (above).

Choices made in the same work (2026-10-29):

- How many full 5-hour windows a full weekly window holds: both tables of what a full window holds, on the history
  page, in the History window and in its export, give it in a column of their own, 5-hour windows in a week (*Rules*,
  *What a full window holds*), after the two windows' figures, and the method note says what it is and how many
  five-hour windows a week holds back to back. It is shown with the range the two figures' rounding leaves it in: each
  figure is good to a tenth of itself, so their quotient can be off by about a fifth, and one decimal alone would claim
  more. It reads — where either figure is unstated or holds no dollars, a rise all of whose use was elsewhere. Revisit
  should the range be found to crowd the tables.
- The window's tray check, which failed while Tk handed its flag back as a list: whether Tk holds the tray icon is
  read as text, which no Tcl type turns into a list. Since 2026-11-07 the icon is Qt's, and no flag is read.

The maintainer's decision on the browser extension's reading (2026-10-29), built the same day:

- The extension's readings reach WindowTally in the file the maintainer confirmed: one per claude.ai organization,
  holding only the latest reading — the time the page received it, the organization, and for the 5-hour and the weekly
  window each its percentage and its reset time (`browser_host`, version 1). The measurement of the page (*Sources*)
  matched it, and no field was added.

Choices made in building the extension (2026-10-29):

- The extension and its host are named after the tool, today WindowTally and `windowtally.browser`: a tool's name
  carries no other company's mark, so the extension needs no name of its own, and the tool carries one name. Revisit
  should the extension be wanted under another name.
- The extension reads only what the page itself received: a script in the page's own world wraps the page's `fetch`
  and reads a clone of each response to the page's own usage request, nothing else; a script in the extension's world
  passes a checked message on to the service worker, which hands it to the host (`chrome.runtime.sendNativeMessage`).
  No request, no cookie, no credential. Revisit should the page stop asking for its usage.
- `install.ps1 -Mode Install` copies the extension and registers its host by default, before the plugin, whose step
  stops the script on a machine with no Claude Code CLI; `Uninstall` removes the host, its key and the copy; `Status`
  reports the host and the copy. The one key does nothing unless the user loads the extension. Revisit should the
  registration be wanted behind a switch.
- The host is a module of the ledger service's package, `python -m windowtally.browser_host <readings folder>`, run on
  the installed copy under the console `python.exe` beside `-Python`'s interpreter — since 2026-11-03 beside the
  installed copy's own, a release's runtime where `Install` copied one there (below) — through a launcher, `host.cmd`,
  that is UTF-8, switches the console to UTF-8, changes to the installed copy's folder and names the readings folder of
  the data folder it was registered for: Chrome talks to a host over its standard streams, which a windowless
  interpreter may not have, and a host manifest's `path` takes no arguments. Revisit should the console be seen to open
  a window when Chrome starts the host.
- The registration is written by WindowTally's Python (`python -m windowtally browser register`, `browser
  unregister`), which `install.ps1` runs from a one-off task, as it writes the Start menu entry: a process inside the
  desktop app has its writes under AppData land in the app's private storage, and its writes to the user's registry
  may land in a private view the same way, which was not measured. The registration takes the registry as a
  parameter, so the tests use one kept in memory. Revisit should registry writes from inside the app be measured
  reaching the registry Chrome reads, which would make the task unnecessary rather than wrong.
- The extension's ID is fixed by a public key in its manifest, `nhabafmhfilijckoeeigflifdjmaicbp`, the one ID the
  host allows; the private key was never written to a file. A test derives the ID from the key. Revisit should the
  extension be published through the Chrome Web Store.
- Browser readings are no instrument for what a full window holds (*Rules*). They read the account's whole use of a
  window, the figure every other reading reads, and every other rule takes them as observations of it — a window's
  figure the highest read, their reset times exact, the weekly anchor read from them. But the plugin's readings, from
  an account's first of them on, and the app's samples before that already divide the account's time between them,
  one instrument at a time, so a run of browser readings would measure spending one of them measures already and
  count it twice. Every account with a browser reading had plugin readings from before its first, so no browser
  reading fell in a span the plugin's readings do not measure (measured on the development machine, 2026-11-02).
  Revisit should an account's first browser reading come before its first plugin reading.
- The host checks a message whole before writing: its version, the organization's UUID, which names the file, its
  time, and its windows — only `five_hour` and `seven_day`, each once, a finite percentage of zero or more with no
  upper bound, and a reset time that is text or null; the ingester reads each file through the same check. A frame it
  cannot read is answered with an error and ends the session, since what follows it cannot be told apart. Revisit
  should claude.ai send a shape the check refuses.
- A browser reading's file is deleted seven days after it was last written, once read, as a plugin reading's is.
- The Coverage section says "Browser readings since …" only where there are any, the extension being optional; it
  says nothing of their absence. Revisit should their absence be wanted said.
- The suite needs no JavaScript runtime: it checks the extension's scripts by reading them — the manifest's one
  permission and its one site, the ID, the host's name and the version the service worker names, no network API
  named; it runs the host in-process and through `cmd.exe` on the launcher with Chrome's two arguments; and
  `install.ps1`'s test of `Status` reads the user's own key for the host without checking what it says. Revisit should
  the suite be given a JavaScript runtime.

The maintainer's decision on what "at its limit" says (2026-10-30), built the same day:

- The band said `every account at its limit` while every account stood past the recommendation's ceilings, though an
  account at 95 % of its week could still be used: the flag meant none below the ceilings, where WindowTally's own
  blocked means 99 %. "At its limit" and the error colour now mean every account blocked, and only then is none
  recommended. While every account is past the ceilings and some are not blocked the band says
  `every account at or near its limit; room returns ↻…` in the warning colour, and `Next:` names the account with the
  highest weekly remaining percentage.

Choices made in building it (2026-10-30):

- status.json gains no field and its version is unchanged: `reliefAt` beside a named account already says the state,
  and a reader written before it tests `account` for null first, so it takes the state for a plain recommendation.
  Revisit should a third state appear.
- The boundary is `CAPPED`, 99 %, in both windows, WindowTally's definition of blocked.
- The near limit's flag takes the warning colour. The window's advice band keeps its normal colours, its critical
  colours saying every account is blocked. Revisit should the window be wanted to mark this state.
- "Room returns" names the first moment an account is below the ceilings again, not the first reset of any window: a
  5-hour reset that leaves its account past 95 % of its week returns no room. Revisit should the first reset be wanted.
- The window's notification *… can be used again* is raised only when an account opens after every account was
  blocked, since an account at or near its limit was usable all along. Revisit should a notification be wanted when
  room returns.
- The choice weighs the week alone, as decided, so an account just below the cap in its 5-hour window can be named over
  one with that window free. Revisit should the 5-hour window be wanted weighed. An account with no weekly figure comes
  after every account with one, since "has the most left" needs a reading behind it; equal weeks go to the earlier reset.

The maintainer's decision on the plan Anthropic renamed Ultra (2026-10-31), built the same day:

- Anthropic renamed the Max 20x plan Ultra on 2026-10-31, keeping its price, features, billing date and weekly limit.
  WindowTally follows it everywhere: the plan's key is `ultra` and its name Ultra wherever a bill, a profile or a list
  price names it — the bills file, `bills add --plan`, the window's bill form and status.json among them — and a bill
  archive's line `Max plan - 20x` reads as Ultra, as does `Claude Ultra`, the line invoices print since the renaming. No
  reading of the former key is kept: a bills file holding it is refused whole, naming the plan, and its bills count in
  no figure until the key is rewritten. Since 2026-11-04 only the bill holding it is left out, the plan named, its
  account said not to be wholly read.

Choices made in building it (2026-10-31):

- One plan, one name across the history: a period billed before the renaming reads Ultra too, since Anthropic's
  notice says the plan is the same, and two keys would read the next renewal as a change of plan. Revisit should
  Anthropic's invoices or limits show the two to be different plans.
- The profile's tier `default_claude_max_20x` names Ultra, and no tier is guessed for it: Claude Code 2.1.310's bundle
  (measured on the development machine, 2026-10-31) spells only `default_claude_max_5x` and `default_claude_max_20x`,
  and a tier WindowTally does not know already shows as no plan it compares. Revisit should a profile name another tier
  or organization type for Ultra.
- No invoice line is guessed for Ultra, as how an invoice under the new name prints it is not known: a line WindowTally
  does not know refuses its manifest, naming the line. Revisit with the first invoice printed under the new name.
- bills.json stays version 1 and status.json version 3, their plan vocabulary changed, and a bills file holding the
  former key is refused naming its cause. The service, the window and the plugin are installed by one `install.ps1`
  run, so a reader of the former vocabulary exists only in a session still running the old plugin, whose panel then
  says the profile names no plan WindowTally compares, where a new version would make it show the whole file as of an
  unknown version. Revisit should bills files holding the former key be found, or a reader be installed apart from the
  service.

The maintainer's decision on accounts with no 5-hour limit (2026-10-31), built the same day:

- Anthropic began on 2026-10-31 to remove the 5-hour limit from Ultra accounts, in stages, account by account; no
  reading from such an account had yet been seen on the development machine. status.json gains a state saying an
  account has no 5-hour limit; every surface — the window's cards, the tray, the band and the panel, the history page
  and the `status` command — says so for that account and leads with its weekly figure; the recommendation and the
  warnings consider only that account's weekly window. A reader installed before it may show
  that account's 5-hour window as unknown until it is installed again.

Choices made in building it (2026-10-31):

- Whether an account has the limit is read off its readings, never set: Claude Code, the browser extension and the
  desktop app each leave out a window the server did not send, and one reading's windows share its source, reference
  and moment. Revisit should a source come to say so in another way.
- One reading without the 5-hour window removes nothing. Measured on the development machine (2026-10-31), Claude
  Code now and then gives a reading carrying the weekly window alone on an account that still has the limit, where a
  5-hour window has just ended or stands near zero: one such reading, or two from different sessions seconds apart,
  and the account's next reading carrying a 5-hour figure follows within minutes. So the limit counts as removed only
  once at least two readings without the window span `NO_LIMIT_SPAN`, 15 minutes, and the next reading carrying a
  5-hour figure restores it. For up to 15 minutes after a real removal the account is shown as before. Revisit should a
  switched account's readings take another shape, a 5-hour figure of zero with no reset time say, or such a passing
  reading be seen spanning 15 minutes.
- The desktop app's samples count as any reading does: none was measured lacking the 5-hour figure, which the app
  writes as zero while no window runs (measured on the development machine, 2026-10-31).
- An account WindowTally reads with the limit removed has nothing inferred for its 5-hour window: the window rule
  applied to its response times would open windows the account no longer has and estimate a rise in each. An account
  with the limit keeps that inference, which serves an account read only through the desktop app's samples or before
  its first plugin reading. Revisit should the inference be wanted gone for every account.
- status.json stays version 3: `no_limit` is one more value of `fiveHour.state`, and the `fiveHour` object stays, its
  figures and reset time null and its `asOf` the latest reading on which the limit stands removed, since the plugin's
  reader refuses a status without it. A reader installed before it reaches its word for a window it cannot place, as
  decided: the plugin's band and panel and the window's card say `unknown`. Revisit should another reader be installed
  apart from the service.
- The recommendation needed no change of rule: a window with no limit is never running and carries no reset time, so
  its ceilings and its first relief already consider the weekly window alone, which the code now says. The plugin's
  toasts judge each reading's own windows, and a reading without the 5-hour window raises no 5-hour warning.
- The words and drawings: the band writes `week …  5h no limit` in full words and `week … 5h none` compacted, and on
  the desktop in-use line, and in the panel, the weekly window takes the 5-hour window's scale and the 5-hour window
  follows at the weekly one's, `no limit` dim with no meter, an empty one reading as a window at zero (since
  2026-11-14 the band shows no 5-hour window for such an account, its weekly window alone, below); the window's
  card shows the weekly block first and a 5-hour block saying `no limit`, `this account has no 5-hour limit`; the tray
  tooltip writes `week … · 5h no limit`, and the tray icon draws one weekly ring as thick as the two rings and the gap
  between them, greyed without a fresh status as the two are (*Rules*, *The logo and the tray icon*); the history
  page's card puts the Weekly row first and a 5-hour row `no limit · this account has no 5-hour limit` with no meter
  (since 2026-11-10 beside one weekly ring as thick as the two, as the tray icon draws it, and since 2026-11-11 beside
  one weekly ring of the weekly ring's own band, the tray icon's unchanged, below);
  the `status` command writes the weekly line first, then `5-hour : no limit on this account`. Revisit should any of
  them prove unclear on an account with no 5-hour limit.
- What a full window holds and the blocked time are unchanged: an account with no 5-hour window simply adds no step
  in it, and its week alone can hold it at its limit.

The maintainer's decision on the folded desktop band (2026-10-31), built the same day:

- Folded, the desktop band's line holds the fold button, then the other accounts — those the unfolded band shows on
  its others' line — in the compact words, smaller and dim, on one line that does not wrap and is cut at the band's
  edge, then the fault flags; where there is no other account, the account in use stands there in the same words. The
  card of every account under the pointer stays, Details stays hidden while folded, and the unfolded band and the
  terminal band are unchanged. A line left empty beside the button was room wasted. Not taken: the account in use
  alone; every account, the account in use first. It replaces the decision of 2026-10-21 that the folded tag stands
  alone, and keeps its ground: the account in use is Claude's own usage indicator's to show, and the plugin is for the
  view across accounts.

Choices made in building it (2026-10-31):

- The accounts take only the room the button and the flags leave: they ask for no width of their own, grow into what
  is left on the first line and are cut there with an ellipsis, in an area that still wraps, so the fault flags, which
  never shrink, wrap onto a further line only when they alone outgrow the line beside the button. The band stays one
  line, a fold hides figures and never faults, and nothing runs past the band's width. Revisit should the folded
  accounts be wanted to wrap, or the desktop app be seen not honouring the cut or the zero width. Since 2026-10-31
  every run of the line is a Text cut at its end, the desktop app having been seen to wrap the line where only the
  whole was cut (the choices made in keeping the folded desktop band on one line, 2026-10-31, below).
- The account in use, where it stands alone, keeps the orange dot it has on the in-use line; with no account in use
  (the desktop app at its sign-in page) every account stands on the line behind the grey dot. The line is never empty
  while there are standings, and the dots keep their unfolded meaning. Revisit should the line be wanted empty for a
  single account.
- The fault flags follow the accounts, each opening with `│ `, in the order the decision names; the accounts give up
  room before a flag does. Revisit should the flags be found pushing the accounts out of sight too often.
- The accounts stand in one run of text joined by ` │ `, not in units with a column between them: one run is what one
  cut needs, and it reads as the others' line does unfolded.
- The line's parts are centred on one another vertically, the accounts' smaller text beside the button's label.
  Revisit should they be found misaligned.

The maintainer's decisions on the name, the logo and the About window (2026-10-29 and 2026-10-31):

- The tool is named WindowTally, a tally of every account's plan windows: written so wherever a person reads it, and
  `windowtally` in its identifiers (2026-10-29; written with a capital T since 2026-11-03).
- The logo is two rings on a dark tile, the weekly window an outer ring in blue and the 5-hour window an inner ring in
  green, and the tray icon is the same rings (2026-10-29). Not taken: the tray's former picture, a light tile with two
  meters, as the logo; a tile of three upright bars in the accounts' colours. Its finished drawing (2026-10-31) is the
  one *Rules* gives (*The logo and the tray icon*): the same at every size the window, the tray and the Start menu
  entry show; in the tray each ring at its own window's level, both at the critical fill while every account is at
  its limit, the tile greyed without a fresh status, one ring as thick as the two for an account with no 5-hour
  limit, the rings in the logo's fixed colours for every account and the rim in the colour of the account in use.
- The README shows the logo as a picture kept in the tree, `images/logo.png`, which a test holds to the drawing
  (2026-10-31); the program itself keeps no image. Not taken: writing the picture only when a copy is published, or
  drawing it a second time by hand as an SVG.

Choices made in building them (2026-10-31):

- The logo is drawn by code from its geometry, with the standard library, never kept as an image: the drawing is
  reviewed as code, and one drawing serves the window's icon, the tray, the About window and the Start menu entry,
  whose icon file the installer's run of the window's code writes beside the packages. Up to 48 pixels every ring and
  gap is a whole number of pixels; above, the geometry is kept as drawn. Each pixel is sampled four by four to smooth
  its edges, so the drawing at 256 pixels takes about a second, and the program draws that size only for the icon
  file.
- The About window carries the copyright line, says that WindowTally is free and under which licence, and names where
  its official copies come from, so that a user sold a copy can find out; it opens the licence and the third-party
  notices a release ships (*Rules*, *The About window*). This settles what the maintainer's decisions on the main
  window of 2026-10-21 left to the tool's preparation for publication (above).
- The licence is the MIT License, in `LICENSE` beside the packages, its copyright line the publisher's, offcutworks.
  The About window reads that line from the file a copy ships, so it is written once; `install.ps1` copies the licence
  into the installed copy, and its Status reports whether that copy matches the source folder's.
- The official copies' address is `https://github.com/offcutworks/windowtally`: the publisher's account and the name
  as written in identifiers.
- The test of the README's picture allows, at a ring's end, what one sample changing sides can move a channel by, over
  at most 64 pixels, far fewer than any change of the drawing moves; its failure names the command that writes the file
  again.

The maintainer's decisions on accounts no longer used (2026-10-31), built the same day:

- The user can hide an account from WindowTally's lists, by hand, account by account, in *Arrange accounts…*; nothing
  hides an account by itself. A hidden account stays in status.json, marked, and every surface that lists accounts
  leaves it out by the mark. Not taken: hiding an account by itself once its bills record a plan that has ended, alone
  or beside hiding by hand; the service leaving a hidden account out of status.json.
- The recommendation weighs no account whose bills record a plan that has ended and none since. Such an account takes
  no readings, so its weekly window, rolled forward through its resets with nothing read, stood at nothing: an account
  no longer paid for was recommended ahead of every account in use, even one at the edge of its week, and "every account
  at its limit" could never be said while one stood.
- An account the user hid that the desktop app or the CLI uses stays listed, so the account in use is never left out
  of a list.

Choices made in building them (2026-10-31):

- Only a recorded plan that has ended leaves an account out of the recommendation: an account no bill names, one whose
  next period is still to come, and every account while no bill source exists are weighed as before, since the bills
  say nothing of whether they are used; the panel and the window's card already say, in the warning colour, that such
  an account has no recorded plan today. Revisit should the bills be wanted to change words only, never what is
  recommended.
- A hidden account is never recommended, even while a client uses it: hiding it says it is not to be used. Revisit
  should a hidden account in use be wanted recommendable.
- The service marks an account `hidden` only where the user hid it and neither client uses it, so that every reader
  leaves out an account by the mark alone and the exception for the account in use is made in one place; absent, the
  account is listed. Revisit should a reader need to know that an account it lists was hidden.
- The history keeps every account, hidden or not: hiding concerns the live standings, and the history's totals must
  not change with it. Revisit should the history be wanted to leave hidden accounts out too.
- *Arrange accounts…* lists every account, the hidden ones included, with a third column, *In lists*, saying `shown`
  or `hidden`, and a check box under the name field, *Shown in WindowTally's lists*; its opening sentence says what
  hiding does, and OK says it saved "which are shown" where it showed or hid an account. The accounts the settings hide
  that the window does not list are kept hidden, as their names are kept.
- An account's hiding is never a conflict in *Arrange accounts…*: having two values, it cannot have been changed in the
  window and in the file each differently, so the window's own change of it is written, and one the window left alone
  is written as the file holds it at OK.
- A hidden account left out of the lists raises no renewal notice, as its renewal tag leaves the band with it.
- The window's header ends its in-use line ` · 1 account hidden` (or `N accounts hidden`), and the panel's foot says
  `1 account is hidden: Arrange accounts… in the WindowTally window shows it again.`, both counting only the accounts
  left out. The `status` and `once` commands list every account and tag one status.json marks `[hidden]`, since they
  show the whole status.
- With every account hidden or its plan ended, none is recommended and nothing is waited on, the reason saying `No
  account is left to recommend: every account is hidden or its plan has ended.` That is no limit: the band raises no
  flag for it, the window's header does not paint it as every account at its limit, and the tray's tooltip gives the
  reason where it would otherwise say `Every account is at its limit`. The window's notice that an account is usable
  again counts every account as at its limit only where a moment the first opens stands, as its header already did,
  so showing an account again after none was left raises no such notice; an all-capped status with no reset time
  known raises none either. Not taken: a cause for the recommendation in status.json beside its reason, which would
  change its contract. Revisit should the reason's words need to be read by a program.
- Settings that cannot be read hide nothing, as they name and order nothing, the problem among the source problems.

Choices made in keeping the folded desktop band on one line (2026-10-31):

- The desktop app 2.42304.0.0 draws a Text cut at its end as one run that does not wrap and ends in an ellipsis, but
  every Text inside it with its own default, wrapping at any point (measured on the development machine, 2026-10-31,
  in the app's own code and in a page drawn with its styles). The folded line was one cut Text holding styled runs, so
  it broke at the end of a run and took two lines, parting an account's name from its figures. Every run of the line,
  the bare text between the styled runs included, is now a Text cut at its end: the line stays whole and ends in an
  ellipsis at the band's edge. The unfolded band and the terminal's band are unchanged. Not taken: cutting only the
  styled runs, which then sit a few pixels off the bare text's baseline; each account a box that does not shrink, in a
  row that clips, which cuts mid-word with no ellipsis. Revisit should the desktop app be seen drawing the line
  otherwise.

The maintainer's decision on a stored login a sign-out in the desktop app ended (2026-11-01), built the same day:

- Where the desktop app, running, leaves its sign-in to an account, and the login WindowTally stored for that account
  holds the very web session the app just ended — the app was put on the account from that stored login, with no
  sign-in to it since — the watcher sets that login aside as a refused switch does, so that the window stops offering
  a switch that is bound to be refused after closing the app for nothing. A login stored from an older, separate
  sign-in may still be good and is kept. An add, which clears the app's sign-in with the app closed, sets nothing
  aside.

Choices made in building it (2026-11-01):

- The witness is the app's own log, the line of each change of sign-in (*Sources*), read against the time the login
  was stored, its `savedAt`. Not taken: comparing the stored cookies with the app's, since the Cookies file is locked
  while the app runs and its values are encrypted. Revisit should a release of the app stop writing that line, or
  write the line of leaving a sign-in at a start or a close.
- The watcher judges whenever the app is no longer on the account its last look found — signed out, or on another
  account — and at its first look at an app at its sign-in page, rather than only when its view turns from signed in
  to signed out: a sign-out followed by a sign-in to another account between two looks shows no signed-out view. The
  account compared is the look's own reading, kept in memory from look to look, since the view is read again after the
  look. Revisit should the app's account be found changing without any look seeing it.
- An ended login is set aside under the name a refused one already takes, `desktop-login.refused.dpapi`, with no
  event, exit code or key of its own: every contract stays as it was, and the window already turns the switch of an
  account with no stored login into *Add an account*. Revisit should the window be wanted to say why an account has no
  stored login.
- Whatever cannot be told keeps the login: no `savedAt`, no log or one that cannot be read, a log that no longer
  reaches back to the store, a sign-in to the account before any sign-out. A login kept that was dead costs what it
  cost before, a refused switch that then sets it aside; a live login set aside would cost a needless sign-in. Revisit
  should dead logins kept so be found to cause refused switches often.
- A switch does not judge the login it is about to put back: the watcher, running from logon, has judged it as the
  app left the account, and the refused switch stays the backstop. Revisit should a missed judgement be found in use.
- A line stamped in the same second as `savedAt` counts as after it: the log's times are whole seconds, and the app is
  closed while a login is stored, so no line of the running app can stand before the store within that second.
- A departure made while the watcher was not running, the app then on another account at the watcher's first look, is
  not judged: which account the app left is not known at that look, and judging every stored login at each start of
  the watcher would read the app's log once per stored login, under the act mutex, at every logon. Revisit should
  such a missed departure be found in use.
- The wait for a sign-in to be saved before a close reads the app's log through the same reader, back through every
  file the rotations left as far as the time it asks for, where it read `main.log` and `main1.log` only.

Choices made in showing an ended plan on the band (2026-11-01):

- An account whose bills record a plan that has ended and none since was drawn on the band as any other, its figures
  rolled forward through their resets to nothing, while the panel and the window's card already said in the warning
  colour that it had no recorded plan today. The band now tags it `plan ended` and, while neither client uses it,
  shows none of its windows; the tray's tooltip does the same. status.json is unchanged: the band and the tooltip read
  the subscription state it already carries.
- The tag reads `plan ended`, in the warning colour, where the renewal tag stands, as the panel and the window's card
  show the state in the warning colour. The two never stand together, the service setting a renewal only while a plan
  is in effect; should a file carry both, `plan ended` is shown, so that the tag always agrees with the windows left
  out. Revisit should the warning colour prove too loud for an account stopped on purpose, when the tag would turn
  dim. Revisited on 2026-11-04 (below): dim on an account neither client uses.
- The windows of such an account neither client uses are left out rather than kept beside the tag: it takes no
  readings, so its figures would read as room left, the reason the recommendation does not weigh it. One a client uses
  keeps them, its readings keeping them live. Not taken: the figures beside the tag. Revisit should they be wanted
  there.
- Every band surface follows the rule — the terminal's line, the desktop's lines, the folded line and the folded card
  — and so does the tray's tooltip; the panel and the window's cards still spell every window out, beside the plan line
  that says the plan has ended. Since 2026-11-04 the band shows such an account's week's reset, the panel and the
  window give it a line of its own, and the tooltip leaves it out (below).
- Only a plan that has ended counts, never one still to come nor an account no bill names: exactly the accounts the
  recommendation leaves out. Revisit should that set change.
- The account is not hidden: hiding stays the user's own act in *Arrange accounts…*, as the maintainer's decisions on
  accounts no longer used (2026-10-31) set it, and a hide made by itself would change what hidden means. Not taken:
  hiding an ended plan's account by itself.
- The tooltip carries no tag for an ended plan's account a client uses, as it carries no renewal tag, and Windows shows
  only 127 characters of it. Revisit should the tag be wanted there.

The maintainer's decisions on tokens over time (2026-10-31 and 2026-11-02), built 2026-11-02:

- The history shows tokens by week, by month and in total, tokens being the unit a user thinks in (2026-10-31). The
  ledger kept every kind of every response, but the page and the window showed tokens only in the models and effort
  tables, each a sum over its range, and every series over time was in API-equivalent dollars, so a change in use
  could not be told from a change in price. What a full window holds stays in dollars: between runs of readings the
  dollars per point held steadier than any one kind of token, so the limits meter close to tokens weighted by their
  list price.
- On the history page, in the History window and in its export the tokens follow the API-equivalent cost charts and
  come before the subscriptions: a chart of each account's tokens per day or per week, on the cost chart's columns; a
  table by week and a table by month, each with a column for each account, every kind of token, all tokens and the
  same responses' API-equivalent cost, the range in all last; and a note saying what each kind counts (2026-11-02).
- The band, its panel and the main window's line of this month's totals show no tokens; status.json and the plugin
  are unchanged (2026-11-02).
- Every one of the History window's summary tiles stands one column wide, as the page's do, *Hours with every account
  exhausted* included, which took two; and the summary gains a tile of tokens (2026-11-02).

Choices made in building it (2026-11-02):

- Every kind is shown: input sent uncached; output, with the thinking inside it beside it as *of it thinking*; the
  cache's writes at both lifetimes in one column; cache reads; and *All tokens*, which counts thinking once, inside
  output. A total alone would hide which kind moved. Revisit should fewer kinds be wanted.
- The chart stacks each account's tokens of every kind on the cost chart's columns and in its colours, so tokens and
  dollars stand column for column, per day and, over 6 months and all, per week from Monday. Revisit should output
  tokens alone be wanted on the chart.
- Tokens are split by account, as the cost is; by model they stay in the models table, a sum over the range. Not
  taken: tokens by model family over time, which would double the charts. Revisit should it be wanted.
- A week runs from Monday and a month by the calendar, in local time, as the cost charts' days do, while the bills'
  months are UTC; the note says so. Revisit should UTC months be wanted.
- In the window the chart and both tables follow the span, so *All* gives every token since the ledger's first record.
  The page, which has no span, charts its thirty days, tables its six weeks — the range of its other six-week
  sections, whose first and last weeks hold only the range's days — and tables its months over the whole history, so
  it too shows tokens over all time. Read for the whole history, the tokens cost a page pass about as much as its
  thirty days of cost already do (measured on the development machine, 2026-11-02). Revisit should a page pass grow
  noticeably slower as the ledger grows, the months table then taking a bounded range.
- Tokens are summed in the ledger by account and quarter hour, then each quarter hour is put on its local day: every
  UTC offset in use is a whole number of quarter hours, so a quarter hour lies within one local day, and a long range
  is not read response by response.
- A table's account columns are the accounts with tokens in its range, in the order they were first seen, the use
  with no known account last, as the cost chart stacks them; its last row, the range in all, is set in bold.
- The *Tokens* tile counts the span's days, the total the token chart adds up to, and stands after the plans' tiles,
  before the shares.
- A tile's least width is its figure or its caption's longest word, the caption wrapping to its column. The columns
  are no narrower than the widest of those, nor than the page's 160 px, grown with the display scale; as many stand as
  fit, never more than the tiles, and of the counts that hold the tiles in the fewest rows the fewest. Measured on the
  development machine with eleven tiles (2026-11-02): at 1860 px they stand in six columns and two rows; at 900 px in
  four columns and three rows, *Hours with every account exhausted* wrapping onto two lines. Revisit should the window
  be wanted to hold more or fewer columns.

The maintainer's decision on claude.ai's use by product (2026-11-02), built the same day:

- WindowTally takes in the split of the week's use by product that claude.ai's usage page shows under *This week's
  usage by product* — Claude Code, Chats, Cowork, Other — through the browser extension, and shows those categories
  beside the weekly window, so that it shows more than Claude Code's own use. It is a pure addition with the way back
  kept: every file and message takes it as an optional key with no change of version, and every part reads, shows and
  decides as before without it.

Choices made in building it (2026-11-02):

- One optional key on each contract, its version unchanged: `weeklyByProduct` in the browser reading, `byProduct` on
  status.json's weekly window (*Contracts*). The host already built its file from the keys it checks, so a host that
  predates the key drops it and an extension that predates it omits it; status.json already admitted keys added with
  no change of version. Not taken: a new version of either. Revisit should a reader need to refuse a file that lacks
  the key.
- The host checks the use by product on its own and never lets it cost the windows: one it cannot take is left out of
  the file, the windows are written, and the answer says why, which the service worker logs to Chrome's console. Not
  taken: refusing the whole reading. Revisit should a use by product out of its shape be wanted to refuse the reading.
- The ledger keeps the reports in a table of its own, `product_shares`, which `open` creates where it is missing, its
  schema version unchanged: a new version would make code that predates it refuse the ledger, and the table holds
  facts no other figure rests on. A reader asks whether the table exists before it reads it, since a read-only reader
  may meet a ledger no pass of this code has opened. Revisit should an existing table's columns need to change, which
  takes a migration.
- Which report is current, and which reports are of one window, are as *Rules*, *Use by product*, says: a window's
  starts are compared within an hour, since claude.ai's start for one window moved by under a second between two
  responses, and a reset time is compared only where it was read. Revisit should claude.ai begin weekly windows less
  than an hour apart.
- A pass reads every account's current report as a phase of its own, *use by product*, after the recommendation and
  before status.json is written: a failure there is a source problem, and status.json and the page are written
  without it.
- The use by product stands inside the regions that already show the weekly window: the third piece of the weekly
  line on the window's cards, beside the weekly window in the plugin's panel, a line on the history page's account
  cards, and a table under the weekly chart in the History window, on the history page and in the export. The band
  carries none, having no room. Revisit should the table be wanted as a section of its own.
- Which products there are, their names and their order are claude.ai's, so a product it adds is carried and shown
  under its own name with no change to WindowTally. A table's columns follow the latest report's order, then products
  only older reports named; a report received again stands as the first reading that carried it.
- No figure rests on it: the recommendation, the warnings and what a full window holds are unchanged. Revisit should
  the shares be wanted to weigh a figure.
- No setting turns it off: the way back is in the contracts, every part reading as before where the key is absent.
  Revisit should a switch be wanted.
- The extension's description says it hands on the week's use by product too, in 129 characters, within the 132 the
  Chrome Web Store allows.

The maintainer's decisions on the history's tables (2026-11-02), built the same day:

- The use by product's table gives, beside each share, the points of the weekly limit it stands for.
- A table has a greatest height, past which it scrolls within itself, so a long table does not lengthen the History
  window or the history page.

Choices made in building them (2026-11-02):

- A table shows its headings and at most twelve rows, its totals among them, in the History window and on the history
  page and its export, both from one number (`history.TABLE_ROWS`), so the two show a table alike: the window sizes
  its rows' canvas by it, the page's style sheet gives a table's panel a `max-height` of the headings and that many
  rows of its text, with room for a sideways bar. Most tables hold fewer rows and are unchanged. Not taken: a setting
  for it, the program setting the height as it sets every other size. Revisit should twelve rows be found too few or
  too many.
- The headings stay above the rows while they scroll, and the total rows at a table's end below them, so a long
  table's sums are never scrolled away: in the window each on a canvas of its own, moving sideways with the rows; on
  the page by sticky positions (`tr.total`), which need no script. A total row among the rows scrolls with them. Since
  2026-11-07 each part is painted by Qt.
- The wheel over a table that scrolls within itself moves its rows while they can move the way the wheel turns, and at
  their top or end moves the view around it (`scroll_model.inner_takes`, through the window's one wheel handler), so
  the wheel never stops at a table's edge; the rows' bar takes the wheel as the rows do. Over the headings or totals,
  or over a table that shows every row, it moves the view. A notch moves the rows as many rows as Windows' setting
  gives lines. Since 2026-11-03 a gesture of the wheel keeps to what took its first turn (below).
- A point is a share of the weekly figure the report came with, written to the whole point: a share in whole
  percents is half a percent either way, so a tenth of a point would claim more than it knows. Below half a point it
  reads `<1 pt`; a share of zero, or one with no weekly figure, stands alone.

The maintainer's decisions on the wheel over the history's tables (2026-11-03), built the same day:

- A gesture of the wheel keeps to what took its first turn: scrolling the History window, the history page or its
  export on, a table that the scroll brings under the still pointer does not take the turns that follow.
- A gesture ends when the wheel rests for a second and a half.

Choices made in building them (2026-11-03):

- The rule is the wheel transaction browsers keep: a gesture also ends when the pointer moves beyond Windows' drag
  threshold (SM_CXDRAG and SM_CYDRAG, read once a gesture, 4 pixels where they cannot be read), measured from where
  the gesture's first turn found it rather than from the turn before, so a pointer drifting a little at each turn still
  ends it. The window and the page take the pause from one number, `history.WHEEL_PAUSE`, beside `TABLE_ROWS`, since
  the page's package does not import the window's. In the window the rule is `scroll_model.gesture_goes_on` and
  `scroll_model.Gesture`, and the whole route of a turn — the walk outwards from the view under the pointer and the
  checks that let a held gesture choose afresh — is `scroll_model.wheel_turn`, which asks its questions of the
  window's widgets through `scroll_model.WheelViews`, so the suite runs it with stand-in views and no display;
  `common_view`'s one wheel handler only finds the widget under the pointer and answers those questions. Not taken: a
  table taking the wheel only once clicked. Revisit should that be preferred.
- A table holding a gesture still passes the turn at its edge to the view around it, which then keeps the rest of the
  gesture, so the wheel never stops at a table's edge. A holder that is gone or stands in another window, or a view
  that can no longer move the wheel's way (`ScrollFrame.can_move`) — the held view itself, or the view a held table at
  its edge would pass the turn to — lets the turn choose afresh, so a table under the pointer is never held still by a
  view at its end.
- The page needs a script for it, which it carried none of before: no style sheet keeps a table's panel from taking a
  turn. One inline script, `dashboard._SCRIPT`, is written into the page and the export by `_document`, and the page
  reads the same without it. While the page holds a gesture, a turn over a panel that could scroll is taken from the
  panel and scrolls the page smoothly, turns arriving within 400 ms adding to where that scroll goes; a turn counted
  in lines takes the body's line height; the threshold is 4 CSS pixels, Windows' default, a page being unable to read
  the setting; Shift, Ctrl and a sideways turn stay the browser's.

The maintainer's decision on the name's capitals (2026-11-03), built the same day:

- The name is written WindowTally, with a capital T, wherever a person reads it, and stays `windowtally` in its
  identifiers (*the name, the logo and the About window*, above). The names by which Windows recognises the program
  that a person reads follow it: its scheduled tasks, its Start menu entry `WindowTally.lnk`, the installed sync script
  `WindowTallySync.ps1`, and the string every stored sign-in is sealed under, `WindowTallySync`.

Choices made in building it (2026-11-03):

- Every task WindowTally registers sits in the Task Scheduler folder `\WindowTally\`, under the short names `Service`,
  `Window`, `Sync` and the one-off `Setup`, so a person finds them together and apart from Windows' own; the sync
  script and the plugin's window button name their task by folder and name. Whichever of `install.ps1`'s `Uninstall`
  and the sync's `UninstallWatcher` removes the folder's last task removes the folder, a failure to do so only warned,
  since an empty folder runs nothing. `Install` refuses while a task at Task Scheduler's root bears the folder's name,
  as Task Scheduler then cannot make the folder (measured on the development machine, 2026-11-03). Not taken: the full
  names inside the folder. Revisit should a task be wanted at Task Scheduler's root.
- `Uninstall`, like `Install`, refuses before it changes anything when it has no interpreter: the Start menu entry and
  the browser extension's host are removed by the installed copy's own code, run under it, before that copy is
  deleted. It says it removed either only when it did. Not taken: removing them without the interpreter, which would
  need a second implementation of both. Revisit should a user need to uninstall without one. Since the release build
  (below), `Uninstall` runs under the installed copy's own interpreter where `Install` copied a release's runtime
  there, so any release's folder, or a source folder, removes such an installation.
- A Start menu entry or an installed sync script whose name differs from its own in capitals alone is removed before
  the new one is written, since Windows keeps a file's own spelling when it is written over under another case; an
  entry spelt as its name is written over in place, so a write that fails leaves it standing.

Choices made in building the release (2026-11-03):

- A release is a zip carrying its own CPython with Tk, as MirrorHold's does, so a user installs no Python
  (*Building a release*). `Install` copies its `runtime\` beside the installed packages, and the installed copy — its
  service and window, the one-off tasks that write the Start menu entry and register the browser extension's host, and
  the host itself — runs under that copy; an interpreter `-Python` names elsewhere, as from a source folder, is used
  where it is, and a runtime an earlier release left in the installed copy is removed. A release's interpreter, with the
  path file its build writes, imports packages only from the folder above its `runtime\`, never from the working
  folder its task starts in (measured on the development machine with CPython 3.14.8, 2026-11-03), so only a copy
  beside the installed packages runs the installed copy; the unpacked release can then be deleted, and `Status` and
  `Uninstall` still run from any release's folder. Not taken: running a release where it was unpacked, which stops
  WindowTally once that folder is moved or deleted. Revisit should a release be wanted to run where it was unpacked,
  `Install` then copying no packages for one. Since 2026-11-07 the runtime also carries the part of Qt the window uses
  (*Building a release*).
- While anything still runs from the installed runtime once the service, the window and the browser extension's host
  are stopped — a command the user started under the installed copy's Python — `Install` and `Uninstall` wait ten
  seconds for it to end, then name it and refuse, ending no process of the user's: Windows refuses to delete a running
  program's file, and ending a command mid-write is worse than a refusal that says what to end. `Install` refuses the
  installed copy's own Python as `-Python`, since it replaces that runtime. Revisit should `Install` be wanted to end
  what still runs.
- A release carries its build record, `build.json`, beside its packages: the release's label and the version of the
  interpreter it carries, and no commit, so that nothing in a release depends on the repository that built it and a
  rebuild of the published repository's tag makes the same zip. Only the build writes it (`windowtally/release.py`);
  the About window names the release by it — `Version 1.0.0, release <label>`, `…, from source` for a copy with no
  record and `…, release unknown` for one whose record cannot be read — the in-code version being the same in every
  release. `install.ps1` copies the record, and the notices, into the installed copy and removes either where the
  folder it runs from ships none, so a copy installed from source names no release. Revisit should About be wanted to
  show the code version alone.
- A release ships what `install.ps1` installs from — the two packages, the account sync, the plugin's manifests, hooks
  and types, the browser extension, `install.ps1` itself, `LICENSE` and `README.md` — with the build's `runtime\`,
  `build.json` and `THIRD-PARTY-NOTICES.txt`; not the tests, the plugin's included, nor this file or the README's
  picture. The notices are Python's, with Tcl/Tk, alone: WindowTally bundles nothing else, its plugin running inside
  Claude Code and its extension inside Chrome. Revisit should a release be wanted to carry the tests. Since 2026-11-07
  they give Qt's, PySide6's and shiboken6's after Python's, a release carrying Qt (*Building a release*).
- `Status` reports the notices', the build record's and the runtime's copies beside the licence's. The runtime is
  compared file for file by the SHA-256 of its bytes, both ways, so a file left over in the installed runtime is a
  difference; a file the folder `Status` runs from does not ship reads as installed with none in that folder; and
  where the console interpreter beside the installed copy's own runtime is missing, `Status` advises installing
  again, `-Python` being unable to replace it.

The maintainer's decisions on accounts whose plan has ended and on shorter words (2026-11-04), built the same day:

- An account whose bills record a plan that has ended and none since keeps only what a renewal is planned around —
  when its plan ended and when its week resets — and none of its windows' figures or limits, so it takes no large
  card; it is greyed, and it stands after every other account by default, which amends the decisions on the order of
  the accounts (2026-10-26). In the window it is a line under the cards. Not taken: a small grey card among the cards.
- Each account's monthly cost at list price leaves the window's cards and the panel, where the decisions on the main
  window after seeing it (2026-10-21) had put it on the plan's line; the window's header keeps this month's totals
  across the accounts.
- Every account's weekly reset carries its weekday.
- The words of the band, the window and the panel are made as short as they can be.

They leave the words of the History, Bills and sources, Arrange accounts and About windows, which the same decisions
take in, to a change of their own.

Choices made in building them (2026-11-04):

- An account whose plan has ended is one whose subscription state is `ended`, the set the band, the tray's tooltip and
  the recommendation already share; an account with no bill recorded, or whose next period is still to come, is shown
  as any other. Revisit should accounts with no bill recorded be wanted set aside too.
- Only such an account that neither client uses is set aside: one the desktop app or the CLI uses keeps its card, its
  panel block and its figures on the band, its readings keeping them live, and stands first as an account in use.
  Revisit should it be wanted compact while in use.
- The order is the service's, so every surface follows it with no reader changed: the accounts in use, then the others
  in the user's order, then those whose plan has ended in that same order (*Rules*, *One order, one name*). *Arrange
  accounts…* still shows the user's own order, and a bill recorded for a new period returns an account to its place.
  Not taken: an account the user placed high keeping its place whatever its plan. Revisit should one be wanted to.
- The window's line: the account's colour as a ring the size of a card's dot — its colour still, as the History
  window's charts use it, but hollow — its name in bold, then `plan ended Sun 1 Nov · week resets Sun 21:59` and the
  e-mail where the name is the user's own, in the page's quieter inks on the page itself rather than a card's raised
  surface, across every column under the cards, with the switch buttons at its end as a card has them. Not taken: a
  grey ring, which would part the account from its colour in the charts.
- The band shows such an account's name, `plan ended` dim and `week ↻Sun 21:59` (*Rules*, *The band*); the panel gives
  it one dim line, as the window does (*Rules*, *The panel*); the tray's tooltip leaves it out, Windows showing 127
  characters of it. None of them gives the profile's word on the plan: the profile an account no client uses keeps is
  the one from its last use, almost always within its last paid period, so its word that no recorded bill covers today
  repeats the bills. A card of such an account in use keeps it. Revisit should the profile's word be wanted everywhere.
- A weekly reset is written by its weekday and time — `resets Sat 04:00 (in 2d 12h)` on a card, `↻Sat 04:00` on the
  band, the tooltip and beside the panel's weekly figure, `in 2d 12h` after it there — its date dropped, a week being
  at most seven days long; a reset more than six days away carries its date, its weekday being today's
  (`Sat 14 Nov 04:00`). The 5-hour window keeps its countdown. Not taken: the countdown beside the weekday on the band
  and the tooltip, which would lengthen them. Revisit should it be wanted there too.
- The words shortened in the window: the header's first line `Updated 1m ago · Desktop app and CLI: <name> · the CLI
  follows the app` where both clients use one account, only the status's age in the warning colour once it is stale,
  and `This month: …`; on a card the reading's age said once, `read 1m ago`, after the last response, where both
  windows rest on one reading or the 5-hour window has no limit, and on each window's line otherwise, without its
  clock time; `reset time inferred` dropped, ≈ saying it; a 5-hour window with no limit its name and `no limit` alone,
  with no meter and no second line; the week's use by product only where two products or more took a share; the plan
  line `Ultra · paid until …`, `ended Sun 1 Nov` or `first period starts …`; the e-mail only beside a name of the
  user's own.
- The words shortened elsewhere: the recommendation's reason `<name> — room left, week resets first (Thu 14:00).`; the
  time left until room returns, or until the first account opens, added once to the moment the reason names,
  `(in ≈1h 05m)`, ≈ where the moment was inferred, where the window's header and the panel said the moment twice; the
  band's fault flags `all accounts at their limit · first opens ↻…` and `all accounts near their limit · room returns
  ↻…`; in the panel the button `Open WindowTally`, `full at this pace ≈…`, `exact reset time` and `reset time
  inferred` dropped, and at its foot no word where there is no source problem, `Updated 1m ago.`, the marks `≈
  inferred, not read · ↻ reset` and `1 account hidden: Arrange accounts… in the WindowTally window shows it.`.
- Kept as decided before: every surface says an account has no 5-hour limit (2026-10-31); the window always counts its
  source problems (2026-10-21; since 2026-11-09 only while there are any, below), so only the panel's foot, a surface of its own, says nothing where there are none; the
  panel spells out every window of each account it shows (2026-10-23), the account set aside above excepted.
- The tray's tooltip names the accounts in use, then `Next:`, then the other accounts; one that runs past Windows' 127
  characters loses the other accounts' lines whole from its end, a `…` line saying so, and what still runs over is cut
  at the limit. Before, the accounts' lines came first and the whole was cut at the limit, so with several accounts
  the line naming the account to use next was the first to go.

The maintainer's decisions on the other windows' words (2026-11-04), built the same day:

- The words of the History, Bills and sources, Arrange accounts and About windows are made as short as they can be,
  as those of the band, the window and the panel were (above); the history page and the History window's export
  follow the History window's, the export being exactly what the window shows (2026-10-28).
- The switch dialogs — Code sessions at work, a CLI that is running, Add an account — are taken into the same change.
- The `status` command's plan line drops each account's cost this month at list price, as the window's cards and the
  panel did, and the command gains one line of this month's totals across the accounts in the window header's words,
  `This month: $… API-equivalent · $… plans at list price · N×`.

Choices made in building them (2026-11-04):

- What a section, a field or a control means stands behind a hint, never as text at rest: in the History window the
  hint of a `?` beside the section's heading, shown on the pointer and on the keyboard focus; on the history page and
  in the export the same `?` inside the heading, its tooltip the hint, and a box under it while Tab has it focused;
  in Bills and sources the hints of the Date, Amount and Period fields, on the name and on the field; in *Arrange
  accounts…* the order's hint on Up and Down and the hiding's on the check box. Not taken: dropping the notes, which
  say what the figures mean. Revisit should a note be wanted on the surface again.
- Kept as decided before: the capacity caveat stays on every surface that shows the measure (2026-10-28), one line
  before the figures, how the measure is counted behind the heading; the note on what each kind of token counts
  (2026-11-02) is the hint of the tokens' heading; the refusal of a name `settings.json` keeps for an account the
  window does not list still names its UUID and says that removing it there frees it (2026-10-27); every switch
  dialog keeps its buttons' words (2026-10-24 and 2026-10-26); the About window keeps every promise it made
  (2026-10-31) — the copyright line, free and under the MIT License, where official copies come from, no network
  request of its own, and the sign-ins kept on this computer and handled by the account sync alone.
- The words shortened in the History window, the page and the export: the headings `Weekly use`, `API-equivalent
  cost per day` (or `per week`), `<name> cost by model family`, `Tokens per day`, `Plans at list price, by month`,
  `Gaps between periods`, `Full window, by plan`, `Full window, by week` and `All accounts exhausted`; the tiles `Top
  model family` and `Hours all exhausted`; the plan words `no plan today · ended …`; the renewal line `Renewal tag: 3
  days before a period ends.`; the coverage's two standing bullets, on Chat-tab tokens and on the API-equivalent cost
  as a yardstick, now the hint of its heading.
- The words shortened in the other windows: in Bills and sources the headings `Bills` and `Sources`, `Add manifest…`
  and `Add bills file…`, the form's `Date`, the reminder `Renewal tag [3] days before a period ends`; in *Arrange
  accounts…* the column `Name`, the check box `Shown in lists`, `default: <name>` beside the name field, the refusals
  `Not usable: …`, and on OK `Accounts saved.`, which no longer says whether an account was shown or hidden, amending
  the choice of 2026-10-31 (above) that OK says it saved "which are shown", as the hint of the check box amends its
  opening sentence; in About `Free, under the MIT License.` and `Official copies only from:`.
- The `status` command's totals line stands before `Next:`, written by the one formatter the window's header uses
  (`billing.month_totals_text`), so the two cannot part. The `bills` command keeps each account's cost this month,
  the decision naming `status` alone. Revisit should `bills` be wanted to follow.

The maintainer's decisions on refunds and on bills not read (2026-11-04), built the same day:

- WindowTally reads a subscription's refund, such as a cancellation's prorated refund, from a bill archive's manifest
  and from its own bills file. A refund ends the plan of the bill it credits on the refund's date, half-open, and after
  that day the account stands ended: no renewal is suggested, it is paid up to no later day, its days with a plan and
  its cost at list price count only the days held, and the profile check reads it as having no bill today. The sum
  refunded is listed beside the bill wherever bills are listed — the `bills` command, the window's Bills and sources,
  the history page — as a record in its own currency, and enters no figure: WindowTally's figures are list price times
  days held and never read amounts.
- WindowTally's own bills file can hold a refund too, pointing at the bill it credits.
- Reading tolerates what it cannot read at the smallest unit: a row a reader cannot read sets aside only the bill it
  belongs to — by invoice number in a manifest, by reference in the bills file — named among the source's problems,
  while the other bills still count; a row belonging to no bill is skipped and named; a missing column still refuses
  the whole file; and writing — the window, `bills add` — stays strict, refusing to rewrite a file it cannot read whole.
  This extends what a bill read twice whose copies disagree already got, and amends, for bill sources, the rule that a
  file the user writes is refused whole (*Contracts*).
- What WindowTally could not read is never shown as what does not exist: no surface states an absence — no bills, no
  bill covering today, an ended plan, a gap, a sum of $0 — whose cause may be a source refused or a bill set aside.
  The accounts it may concern say their bills could not be read, pointing to the source problems, and this month's
  plans at list price is not given as a known figure while any bill is unread, on the window's cards and header, the
  `status` command, the history page and the plugin's panel alike.
- A refund in the bills file is an entry of the kind `refund`: its account, the day it was issued, the sum returned,
  unsigned, in the credited bill's currency, and that bill's reference, required, with an optional note and neither a
  plan nor a period; the file stays version 1. A file without refunds is unchanged, and a WindowTally that does not
  know the kind refuses a file holding one by naming it. Not taken: a change of the file's version.
- status.json says that bills could not be read by the subscription state `unread` — its plan, plan name, paid-until,
  days left and month's sum null, no renewal tag, the profile not compared — and by the top-level `billsUnread`,
  written only as true, the month's plans at list price then null; it stays version 3, so a reader still
  running older code refuses the whole status until it is restarted, and never says that an account has no bills. Not
  taken: a change of version, and the plan the bills read give shown beside a warning.

Choices made in building them (2026-11-04):

- An account's bills are not wholly read where a bill WindowTally holds was not counted: every account's while a
  source is refused, a listed source does not exist, the settings cannot be read, so which sources there are is not
  known, or a bill left out names no e-mail; one account's where a bill or row of it was left out, a bill of it read
  twice has copies that differ, or a refund of it matches no bill or contradicts its bill. Revisit should unreadable
  settings, a missing listed file or a differing copy be wanted stated as before.
- An account not wholly read states nothing — no period, gap, use, plan, paid-until, reminder, profile comparison or
  cost — since anything derived from part of its bills may be wrong either way, a refund or a renewal among those not
  read; its bills read are still listed. It is not an account whose plan has ended, so it keeps its card and its place
  in the order and the recommendation weighs it, as it weighs every account while no bill source exists; what a full
  window holds does not measure it, the bills giving it no plan. Revisit should the plan the bills read give be wanted
  shown beside a warning.
- While any bill is unread the history's surfaces qualify every absence an unread account may contradict: the
  summary's *Plans at list price* reads `not known`, with no multiple; a note under the subscriptions' summary says
  that some bills could not be read and that the figures below leave out the accounts they may concern; the cost table
  holds the accounts read alone; and the coverage, a gap's cover, the gaps table's `None` and a plan no account held
  are said `by the bills read` or `among the accounts read`. Revisit should those figures be wanted withheld whole
  rather than qualified.
- A refund is set against its bill in both sources: the same currency, no more than the bill charged, dated on or
  after the bill and, for a bill with a period, before its printed end — a refund after the end can end nothing;
  otherwise the bill and its refund are left out. A refund matching no bill counted is left out alone. Two refunds of
  one bill are two copies of one document: agreeing, they count once; differing, both are left out. A refund dated on
  or before its period's start leaves it no day held, and the account then stands ended rather than with a period to
  come; where no period held a day it ended on the last refund's day, never on the later day a refunded period would
  have begun.
- A refund may credit a bill of any kind, since a credit note can carry any line; only a subscription's ends a plan,
  and a refunded top-up is just listed. Revisit should refunds of top-ups be wanted refused.
- Refunds are matched to their bills across sources, by account and reference, once every source is read, so a refund
  in the bills file can credit a bill in a manifest.
- In a manifest: a refund's own document without its credit note leaves out the bill, as a receipt without its invoice
  does; a credit note names its invoice's account, line item and printed period, or the bill is left out; a paid row
  with no invoice number is left out alone, its account not wholly read; a voided row is skipped whatever its document
  type, a voided document reaching no total; and a row that cannot be read still stands for its document, so that its
  bill is not also said to lack that row.
- In the bills file, an entry that breaks the contract leaves out every entry of its account and reference — of its
  reference alone where its account cannot be read, the account then being the one the entries left out name, or
  every account where they name none or several — and one with no readable reference is left out alone. Narrowed to
  the account so that another account's bill of the same number is never left out unnamed.
- A reader that reads whole stands beside each that reads bill by bill: a writer and the listing of a source read a
  file whole and refuse it with every problem named, in the words they used before; a pass reads bill by bill.
- Listing a further source stays strict: a file is listed only once it reads whole, the one moment the user is there
  to put it right; a source already listed is read bill by bill. Revisit should a source be wanted listed while it
  reads only in part.
- The days with a plan, how far an account is paid up, its state and the coverage are read from each period's days
  in effect, not from its printed end, so that a plan a change replaced does not come back when its replacement is
  refunded. For bills without refunds the figures are unchanged save where a period starting inside another ends
  before it: the earlier plan then no longer counts after the later one ends, which is what "in effect" already said.
  Revisit should the earlier plan be wanted to resume then.
- The cost of the days held follows the rule for a period cut short: the price per printed day on the days in effect.
- A refund is listed as *Rules* (*Where a refund is listed*) says. The writers — `bills add` and the window's record
  and change — set a bill and its refund against each other first: a refund must credit a bill read and agree with
  it, a bill must agree with the refund that credits it, and a bill and a refund left out for contradicting each other
  count there, so either can be put right by changing it.
- The words: a card's plan line `bills not all read · see the source problems`, in the warning colour, as the history's
  plan words; the `status` and `bills` commands `its bills could not all be read; see the source problems`; the
  totals `plans at list price not known: some bills could not be read`; the panel `bills not all read · see Source
  problems below`; the profile's word `not compared with the profile: the account's bills could not all be read`,
  left out where the plan line already says it.
- Bills and sources gives a source read in part as its bills and how many it left out, its Bills column widened to
  hold both; a bills file with a broken entry lists its readable entries, read-only, writes to it being refused in
  any case.
- The window and the plugin take a null month's sum only with the state `unread`; any other null is still not the
  version-3 shape.

Choices made in making writes reach the disk (2026-11-06), after a crash left the sync's `state.json` in zero bytes
and the CLI stopped following the desktop app:

- A write flushes its temporary file to the disk before the move (*Rules*, *Writes*), rather than writing through on
  every write or keeping a backup copy: it closes the failure measured, bytes not on the disk when the journaled move
  survived, at one flush per write of files that are small. Revisit should a crash still leave a file in zero bytes.
- A `state.json` that is not a JSON object stops every look and says to remove it, rather than being read as absent:
  read as absent, the next look would trust whatever label `~/.claude.json` names, the very check the file exists
  for. Revisit should the sync be wanted to set such a file aside itself and go on.
- A read the system refuses is not called damaged, the file being whole; only a text that is not a JSON object is.
- An error naming a file that is not a JSON object carries the parser's own message, save for the CLI's sign-in file,
  whose text the parser would quote: a sign-in's text never reaches a message or the log.

The maintainer's decision on the window's toolkit (2026-11-06), built by 2026-11-07:

- The window, its tray icon and its notifications move from Tk to Qt, through PySide6, for a better-looking window
  than Tk draws. The service imports no toolkit and is not part of the move. The move changes how the window draws,
  never what it shows, asks or does: every figure, word, action and rule stays the models', the service's and the
  decisions above, and each window keeps its regions where they stood.

Choices made in building it (2026-11-07):

- Qt Widgets, not QML: the window stays Python alone, its models computing what it shows and its views drawing it,
  with Qt's painter for the cards' marks, the charts and the tables. Revisit should a wanted effect need QML's
  animation. Since 2026-11-09 the maintainer's decision (below).
- Qt's own Windows 11 style in WindowTally's colour roles, through one palette and one style sheet set at first paint
  and at every change of mode; off Windows 11, where that style's icon font may be missing, Fusion, which draws every
  control the window uses too. The title bar follows the light or dark mode through the colour scheme Qt asks Windows
  for, with no call of the window's own (since 2026-11-09 tinted to the page colour on Windows 11 too, below). Not
  taken: a Fluent widget library, whose licence, the GPL, does not fit
  WindowTally's MIT licence; Windows' Mica backdrop.
- Inside the regions (the main window's since 2026-11-09 in the restrained dashboard look, below): cards with rounded
  corners and a hairline edge, rounded meter tracks, hover states, the
  clients' roles on a card as small coloured chips (`desktop app`, `CLI`, `use next`; since 2026-11-11 of one neutral
  tint, below), the History window's spans as
  one segmented control, the chosen one filled, and smoothed stepped lines and stacked columns with rounded tops. The
  smoothed round marks drawn as pictures for Tk's canvas went, Qt's painter smoothing every mark itself; the wheel's
  rules and the tray icon's check stay.
- Qt enters as PySide6-Essentials with shiboken6, 6.12.0, never the PySide6 package, which also brings Qt's add-ons,
  web engine and PDF modules, none of which the window uses; a release carries only the part of it the window and its
  platform need (*Building a release*).
- A history table stays painted from its layout rather than being one of Qt's item views: an item view scrolls
  itself, so the wheel's rules over a table — a gesture kept to what took its first turn, a turn at the rows' edge
  passed to the view around them — would not hold, and nothing in a table is chosen. The lists of the Bills and
  sources and Arrange accounts windows are Qt's tree lists, which scroll themselves, as Tk's did. Revisit should a
  list need the wheel's gesture rule.
- The window's questions — removing a bill, stopping reading a bill source, the questions before a switch — are its
  own dialogs, wearing its palette; the file dialogs are Windows' own (measured with Qt 6.12.0 on the development
  machine, 2026-11-07), following Windows.
- The tray icon is asked of Windows as before: Qt says nothing of whether Windows holds it, and adds it again when
  Explorer re-creates the taskbar (Qt 6.12.0, measured on the development machine, 2026-11-07), while an icon Windows
  refused at its first add could not be made to happen there, so nothing showed Qt recovering from that. While the
  icon is missing it is made again by hiding and showing it. Revisit should Qt be found to recover from a refused add
  itself.
- The window's record keeps its place as before, in the display's pixels, so a record written by the Tk window opens
  the Qt one where it was; every start keeps its command line, and the logon task, the Start menu entry and the
  plugin's button open the Qt window with nothing registered again.
- `Install` refuses, before it changes anything, an interpreter that cannot import PySide6's Qt Core, Qt GUI and Qt
  Widgets, which would leave a logon task that never opens a window. It asks in a process of its own, with Python's
  environment variables and the working folder kept out, which the logon task's start does not have; a release's own
  interpreter carries Qt and is not asked. Not taken: a least version, a release pinning its own.
- Tk stays in a release's runtime though the window no longer imports it: the runtime with Tk is the release core's,
  taken by every program the core builds, and taking Tk out of WindowTally's alone would change that core in every
  copy for Tk's part of the zip, about 3.5 MB (measured on the development machine, 2026-11-06). Revisit should Tk be
  wanted out of WindowTally's runtime.

The maintainer's decision on sessions across accounts (2026-11-07), the first part built by 2026-11-08, the second
by 2026-11-09:

- A Code session the desktop app leaves behind at a switch of account can go on from the account switched to: the
  window offers the sessions of the account the app leaves and opens those chosen on the other. The switch dialog's
  regions were approved from a sketch: the account switched to named; the sessions listed, each with a tick box, its
  title, a mark where a limit stopped it or it is working, and its last activity; under the list, that permission mode
  and effort are set again in each session; and the buttons Wait and switch, Switch and Cancel.
- Every account's Code sessions stand in one window, from which a session opens on the account in use. Its regions
  were approved from a sketch: a row of a search by title, an account filter and a project filter; the list's Title,
  Project, Account, Last activity and Used; a line naming the account a session opens on; and the buttons Copy resume
  command and Open session. It is reached from a Conversations button in the main window's bottom row (since
  2026-11-11 at the right end of the header's line, below), the File menu and the tray menu.

Choices made in building the first part (2026-11-07 and 2026-11-08):

- The window reaches the desktop app through the app's resume link, `claude://resume?session=<id>`, and writes
  nothing of the app's own. The link had the app adopt a session of another account under the account it was signed
  in to, which then answered there (measured on the development machine, 2026-11-07, desktop app 3.6556.2.0), while a
  card WindowTally wrote into the app's store would rest on a layout no update promises. Revisit should an update
  change the link, or the link be found refused right after a switch.
- A session's title comes from its transcript, not from the app's session cards: the service reads the transcripts
  already, so no new source enters, and the cards' titles stand in the transcripts' own lines (*Sources*). Its last
  `custom-title` is its title, else its last `ai-title`, and a title of no words is none. Revisit should the app's
  titles stop matching its transcripts', or a surface need what only a card holds.
- A limit stop is a main session's line flagged `isApiErrorMessage` with `error` `rate_limit`, its window and reset
  recorded where the line names them and unknown otherwise; a subagent's is not recorded, being its parent's turn's.
  Revisit should Claude Code write a stop otherwise.
- The transcripts already read are read once more by a catch-up that reads only title and stop lines (and, since
  2026-11-11, the lines naming a permission mode, below), only the part already read of each main transcript, and once, recorded in the ledger's meta table, rather than read again whole,
  which would upsert every response again, the whole work of a first import. The titles and stops go into tables of
  their own, `session_titles` and `limit_stops`, which `open` creates without a change of version, as it creates
  `product_shares`: they add facts no other figure rests on. Revisit should a later kind of line need the responses
  read again anyway.
- A limit stop takes the account a response of its session would take at its moment (*Rules*, *Attribution*), being a
  request of the account in use refused, so a session stopped right after it was taken along is listed under the
  account that stopped it. Revisit should attribution's rule change.
- The sessions offered are the desktop app's Code tab's of the last day, with those the markers say are working (since
  2026-11-11 those the session registry says are at work, below): a stopped session that was gone on with was gone on
  with within hours, and older sessions are not what a switch is made to take along. The stopped stand first and are
  ticked with the working; which of the rest are ticked is the decision of 2026-11-10 below. Revisit should a stop be
  found answered later than a day.
- The window runs a pass before it offers the sessions only where a marker was written after the last status, a stop
  seconds old being the usual reason to switch, while a switch with no Code activity since the last pass stays as quick
  as before; a pass already running is not waited for. Revisit should the plugin's markers stop marking a turn's start
  and end. Since 2026-11-11 the registry stands in for the marker: a pass runs first while a session of the app is at
  work, or where its status changed after the last status (below).
- With no session to take along, a switch asks what it asked before, so the question before a close and its tests stand
  unchanged.
- The links open only after a switch that ended done, one at a time and two seconds apart, the first two seconds after
  the end, through the shell's own opener; the gap is not measured. A switch that left the app at its sign-in page says
  the sessions chosen were not opened, and a refusal or a cancel leaves them on the account still in use. Revisit should
  the link be refused right after a switch.
- While the sessions are read or chosen no other of the sync's jobs begins, since it would take the flow the switch is
  about to need; while they are opened a switch or an add of the app is refused, since it would close the app under
  them, while a switch of the CLI, a turn of a switch and a start of the app may run.

Choices made in building the second part, the Conversations window (2026-11-09):

- The list holds the sessions of the desktop app's Code tab and of the CLI, not the runs of the SDK and of
  `claude -p`, which Claude Code's own list of sessions to resume leaves out too (Claude Code 2.1.310, read in its
  program on the development machine, 2026-11-09). Revisit should headless runs be wanted in the list.
- Open session hands the desktop app only a session its Code tab ran, and a session the CLI alone ran opens with its
  resume command: the resume link was measured adopting the app's own sessions (desktop app 3.6556.2.0, 2026-11-07),
  and a session the CLI alone ran has no card in the app. Revisit should the link be found adopting such a session.
- No link is handed on while the app is not running, at its sign-in page, while one of the sync's jobs runs or a
  switch is being prepared, or while the status cannot name the app's account: starting the app is the sync's work,
  and a link would start it around the sync; at its sign-in page it would land on no account. Revisit should starting
  the app stop being the sync's alone.
- A session's project is the folder it was started in, its first main answer's, since the folder a line names moves
  with every change of directory (*Sources*); a working copy Claude Code made inside a repository stands under the
  repository, so its working copies do not crowd the project filter; and the switch's dialog names an untitled
  session by the same folder, so a session has one name on every surface. Revisit should the folder a session last
  worked in be wanted instead.
- The resume command is PowerShell's, as every command the README gives, and changes to the session's own folder, or
  to none where that folder is gone — never to the repository of a working copy since removed, where the session
  would go on writing in a folder it never worked in. Claude Code finds a session by its id beyond the current folder
  (Claude Code 2.1.310, read in its program on the development machine, 2026-11-09), so the folder is for the work,
  not for the finding. Revisit should a build of Claude Code stop finding a session outside its folder.
- Used is what the session's answers, its subagents' included, would have cost at API prices, in dollars, as the
  History window counts use. Not taken: tokens. Revisit should tokens be wanted.
- A session's account follows the rule of the switch's dialog, one function deciding for both surfaces: its latest
  answer's, or that of a limit stop standing after it, a stop not yet given an account leaving it its latest answer's.
  A session no account could be given to says *no known account*, the History window's words, and has an entry of
  its own in the account filter.
- Every account's sessions are listed, hidden accounts' included, as the History window keeps every account.
- Return in the search goes on to the list and opens nothing: opening takes a session into the account in use, which
  a search should never do by itself.
- The list is read off the window's thread, when the window opens, on F5 and after each new status while it shows: a
  large ledger takes long enough to stall the window. The line follows the status each second, so it says at once that
  the app was switched or stopped.
- A conversation the desktop app went on with in a new transcript stands as two sessions, as in Claude Code's own
  list: no transcript line joins the two (*Sources*), only the app's cards do, and the window reads no card, a
  session's title coming from its transcript. Revisit should the app's cards be wanted read for it.
- A session at work gets no resume command, since a second Claude Code writing beside it would interleave its
  transcript; Open session still shows it in the app.
- The window stays on top with the main window while keep-on-top is on, as the Bills and sources window does: it opens
  from the tray while the main window is hidden.
- No table is added: the ledger already held each answer's folder and entry point.

Choices made in keeping the window's words on the screen and the Bills and sources form's typing (2026-11-09):

- A hint's or a chart mark's words that would pass the right or bottom edge of the screen's working area turn to the
  other side of what they belong to — the pointer, or the control — and are then held inside the area, rather than
  only being held at the edge, which at a corner of the screen would put them under the pointer: the pointer would
  leave the chart for the words, which then hide and show again. A hint asked for under its control goes above it;
  words that fit on neither side are held at the edge, and stand over what they belong to only when that is so both
  across and down. The area is that of the screen the words are asked for on, else of the one what they belong to is
  on. Revisit should words be found misplaced on a display of several monitors.
- The wheel over the form's account drop-down, its field included, picks nothing and goes on to what is around it: a
  pick of an account fills the form anew for it, so a notch of the wheel there would lose the date, amount, invoice
  and note typed, with no question. The wheel over the kind drop-down still picks as its list does, the form keeping
  what was typed. Not taken: the wheel changing the account while keeping what was typed, which would leave one
  account's form holding another's defaults.

The maintainer's decisions on the window's look (2026-11-09), the main window built the same day:

- The window takes a restrained dashboard look: a dark, technical dashboard drawn with Qt's painter, held back, since
  many effects read as tacky. Not taken: Windows 11's own look refined; a rewrite in QML with ambient effects.
- Qt Widgets stays; no QML.
- One design language in two modes: the dark mode its showcase, the light mode its counterpart in the same language.
  The theme's choices stay Follow Windows, Light and Dark, with no fourth.
- The default theme stays Follow Windows.
- Three things move from always shown to shown when they matter, each bound derived by the program from the data,
  never a setting: a reading's age, only once the reading is old enough that its figures may be out of date; a plan's
  days left, only when its renewal is near, its date always shown; the source problems' line and its Show button,
  only while there are problems. This narrows the decisions above that the window shows live every figure status.json
  carries, that it always counts its source problems, and that every word stays shown.
- On a card the two windows' rings replace each window's bar: one gauge per figure, and no bar on a card. Not taken:
  the bars kept beside the rings, each figure drawn twice. Since 2026-11-11 a per-model window, which has no ring,
  stands under the rings as a thin bar, the two windows' rings standing as they were (below).

Choices made in building the main window (2026-11-09):

- Restraint: glow only on data — the rings — and on the account in use (since 2026-11-11 on data alone and in the dark
  mode alone, below); no ambient motion — no aurora, particles,
  shimmer, tilt, frosted glass or overshoot. A ring moves only when its figure changes, sweeping to the new value once
  in 0.6 s, easing out, never on the window's first showing, and a window at a warning or an error level pulses
  slowly and lightly, every 3.4 s, down to 0.58 of its strength. With Windows' animation effects off nothing moves,
  the setting read at every start and every frame (`SPI_GETCLIENTAREAANIMATION`, which by Microsoft's documentation
  the Animation effects switch sets). One clock draws every frame and runs only while something moves: every 40 ms
  while a ring sweeps, every 100 ms while rings only pulse, once a second while every moving ring stands in a
  minimized window; at rest no timer runs. Revisit should a pulse's cost be felt.
- A card's rings echo the logo and the tray icon: the weekly window outside in the logo's blue and the 5-hour window
  inside in its green, each arc taking the warning or the critical fill at those levels as the tray's rings do, drawn
  clockwise from the top with flat ends on a track; an account with no 5-hour limit draws one ring as thick as the
  two, and a window not started its track alone. The rings stand square at the left of the windows' lines, 4.6 lines
  of the default font, a dot of each ring's colour before its window's name; the plan stands under a hairline. Since
  2026-11-11 the rings are thinner, 3.2 lines square, beside the two windows' names and figures alone, and an account
  with no 5-hour limit draws its weekly ring no thicker (below). In the
  dark mode an arc carries a soft halo of its own colour, painted as wider translucent strokes, never a graphics
  effect, which would render the card offscreen at every second's update; the rings paint their own square, so a
  frame of a pulse repaints them alone.
- The card of an account a client uses is edged in the account's colour, with a soft glow of translucent strokes
  inside the edge; under the pointer every card still shows the focus edge. Since 2026-11-11 a strip of the account's
  colour inside the card's left edge marks it, with no glow, and no card's edge changes under the pointer (below).
- The page ground: the page colour under a fine grid every 24 pixels, one step off the page, painted only over what a
  repaint asks for, so the cards' updates each second cost it nothing. Since 2026-11-11 the grid is the dark mode's
  alone (below).
- The title bar is tinted to the page colour through Windows' caption colour on Windows 11, on every window with a
  title bar as it shows and on every one shown at each change of mode; elsewhere nothing is called. Measured with Qt
  6.12.0 on the development machine, 2026-11-09, Windows 11 build 22621: a window and a dialog take the colour in each
  mode, and keep it while only Qt's colour scheme changes. Not taken: Mica, which tints by the wallpaper.
- Words in Segoe UI Variable Text, else Segoe UI; figures in Cascadia Mono, else Consolas, semibold, so every digit is
  one width and a changing figure never shifts what follows it. No font is shipped; where Cascadia Mono is missing Qt
  takes Consolas (Qt 6.12.0 found Cascadia Mono installed on the development machine, 2026-11-09). Since 2026-11-11
  figures are in the words' family with its tabular digits (below).
- The colours: in the dark mode a blue-black page, `#070b12`, and cards one step off it, `#101a28`, standing apart at
  1.13:1; in the light mode a pale, cool page, `#edf1f6`, and white cards; inks tinted toward the logo's blue; every
  account's colour unchanged; every text at 4.5:1 or more on what it is written on, as before. A card's and a tile's
  hairline edge, a ring's empty track and the page grid are opaque colours of their own in both modes.
- Push buttons, the menu bar and the menus, the tray's menu included, tips, the scroll bars — thin, with no arrows —
  and a drop-down's open list are drawn the look's own way in every state the window puts them in; the check boxes and
  the drop-down itself stay Windows 11's, drawn from the colours. Lists and their headers keep their former edge.
- A reading's age is said where there is no reading, where a response came after the reading, which the reading then
  does not hold, or once the reading is five hours old, the shortest span over which an account's standing renews. A
  plan's days left are said within one week of its renewal, the longest span its limits renew over, never by the
  renewal reminder's days, which are a setting; the renewal's tag still follows the reminder. Revisit should readings
  be found taken routinely before their own response, or another span be wanted.
- The header names which account each client uses only where the cards' chips cannot: the desktop app not running or
  at its sign-in page, or an account in use the status does not know. While the window starts the app the clause
  stays hidden, the chips and the progress line saying it. The sync's mode and the hidden accounts' count are always
  said.
- The line under a 5-hour window not started, *the next message opens a window*, goes: explanation at rest.
- Every other word, every window's regions and the release's Qt — Qt Core, Qt GUI and Qt Widgets alone — are as they
  were.
- Measured on the development machine, 2026-11-09, on an invented machine: the main window's processor time at rest
  stays under 1 %, as before, and about 1.7 % while one ring pulses.

The maintainer's decision on the sessions a switch ticks (2026-11-10), built the same day:

- A switch of the desktop app also ticks, at the start, the sessions used just before it. A session whose turn had
  ended a minute before a switch stayed with the account left, unticked as every idle session then was, where the
  maintainer expected it taken along. Offered the ticks as they were, or with the sessions active in the 15 minutes
  before the switch added, they chose the second.

Choices made in building it (2026-11-10):

- A session of the rest is ticked while its last activity lies within 15 minutes before the switch (`JUST_USED`), the
  stopped and the working ticked as before: a switch is made to go on with the work in hand. The 15 minutes are
  counted from when the switch was asked for, so the pass it may wait for first takes no session out of the ticked.
  At a switch, 15 minutes took in the few sessions just used, where half an hour and more took in sessions left
  earlier (measured on the development machine, 2026-11-10). Revisit should 15 minutes tick too many or too few.
- The dialog says above the list that a session left unticked stays with the account left and that the Conversations
  window opens it later: a session not taken along was taken for lost.
- A list draws its own tick boxes (`common_view.TickDelegate`) from the palette's accent, field and placeholder ink,
  each pair at 3:1 or more on a row's field, hover and selection in both modes, which the suite measures. Inside a list
  the style sheet gives a frame, Windows 11's style drew a ticked box blank and an unticked one as a box, so each read
  as the other (measured with Qt 6.12.0 on the development machine, 2026-11-10: the tick returned once the sheet held
  no rule for the list). Not taken: an indicator rule in the style sheet, which needs a picture file for the tick;
  the list left without its frame. Revisit should the style draw the tick again under a sheet.

The maintainer's decision on sessions whose background work is unfinished (2026-11-10), built the same day:

- A session whose turn is over while a background task it started has not ended is taken along by default too: its
  work is not done, and left behind it is forgotten and never run. Told that the task itself does not go on with the
  session and has to be run again on the account switched to, the maintainer chose to have such a session ticked all
  the same.

Choices made in building it (2026-11-10):

- The service reads a background task's start and end from the transcripts, which it reads already, into a table of
  its own, `background_tasks`; the plugin and its markers are unchanged, a marker saying only whether a turn is in
  progress (since 2026-11-15 the plugin writes no markers, below). A task with a start and no end is unfinished,
  whether it still runs or went with a client that closed: the transcripts cannot tell the two apart, and either way
  the session's work is not done. Revisit should Claude Code write a task's start or end otherwise (*Sources*).
- An end is matched by the task's id in any transcript, not only its session's: a session whose process had gone was
  gone on with in a new transcript, which got the stopped task's notification, and matched within one transcript the
  first would stand as unfinished for a day and be taken along again.
- A notification ends only the task it opens with, and only where it names a status before its summary, the summary
  being free text that may quote another task's; a stop the session made is known by its result's message, so a tool
  that only asks about a task ends none. Every notification read opened with its task's id and named
  its status, where it had one, before its summary (measured on the development machine, 2026-11-10). Read the
  other way a task would be taken for ended that still ran, and its session left behind unmarked; a stop worded
  otherwise by a later Claude Code leaves a mark too many instead.
- A task started again under its id, a subagent gone on with, keeps its latest start and its latest end, and is
  unfinished while the end stands before the start. The rows are kept, as every fact the ledger reads is; they are few
  beside the responses.
- A session's unfinished tasks are those it started within the day a switch offers sessions over (`CARRY_SPAN`), so a
  task that never reported back does not mark its session for ever. Few tasks started are left with no end (measured
  on the development machine, 2026-11-10).
- A task that only watches, whose notifications are its events, is not work and is not read; a subagent's own
  background task is its parent's turn's, as its limit stop is.
- Such a session stands after the working and before the rest, *Background work unfinished*, ticked however long
  ago it was last active; one a limit stopped or one at work says that instead, and the dialog's line on running the
  work again is said for it all the same. Wait and switch does not wait for background work, whose end may never
  come.
- Background tasks are not caught up from the part of each transcript already read, as titles and stops were: only
  those of the last day are asked for, so a ledger this code first opens lacks them for at most a day.
- The Conversations window does not mark such a session. Revisit should it be wanted there.

Choices made in carrying the look into the other windows (2026-11-10):

- The History, Bills and sources and Conversations windows stand on the page ground, its fine grid included, as the
  main window does; Arrange accounts, About and its window of text, and the questions before a switch stand on the
  plain page colour: a grid behind a few lines and buttons would be ornament. Revisit should the grid be wanted there.
  Since 2026-11-11 the page ground lays its grid in the dark mode alone, in these windows as in the main one (below).
- The History window's summary draws each account's share as a thin bar in the account's colour under its figure. The
  share and the account's colour come with the figures from the history, as the tile's caption and figure do, so the
  window computes nothing of its own and the history page can draw the same bar from the same tile. Every tile keeps
  the bar's room, so the figures of a row stand at one height.
- Under each line of a chart a shade of the line's colour fades from the line's highest point to nothing at the
  baseline, at 0.14 of the colour in the light mode and 0.20 in the dark, laid under the gridlines so a rule stays
  crisp across it. In the dark mode each line also carries a soft glow, one stroke of its colour 2.8 times its width
  at 0.14, under it; in the light mode, where it does not read, none. The columns, filled already, carry neither, and
  keep their rounded tops. A line can hold thousands of points and its glow costs several times the line itself, so
  the shades and the lines are painted once for a size, a mode and a display scale and laid down at each repaint,
  never through a graphics effect. Revisit should the pictures' memory be felt. Since 2026-11-12 the History window's
  shade under a run of readings fades at its floor, the baseline unless the run is narrow (below).
- A history table stands as a panel on the cards' surface, edged by their hairline and rounded as a card: its
  headings in the quieter ink above a hairline, its rows parted by the faint gridline, its totals under a hairline.
  The headings' column rules go, the look's tables having none. Revisit should the column rules be wanted back.
- Lists, text fields, check boxes, drop-downs and the read-only text stay Windows 11's own drawing from the colours,
  which reads in both modes; lists keep their edge. Every word and every window's regions are as they were. Since
  2026-11-12 a list marks the row the keyboard is on with a strip of the focus colour rather than the style's frame
  (below).
- Measured on the development machine, 2026-11-10, on an invented machine: the window's processor time with the
  History window open at rest stays under 0.1 %, as before.

The maintainer's decision on the history page's look (2026-11-09), built on 2026-11-10:

- The history page, and with it the History window's export, takes the window's restrained dashboard look, in the
  same two modes.

Choices made in building it, and in making the README's pictures again (2026-11-10):

- The page stands on the page ground under the window's fine grid, every 24 pixels; its cards, tiles, charts and
  tables are panels on the cards' surface with the hairline edge, rounded as a card; its figures are in Cascadia
  Mono, else Consolas, else the browser's monospaced face, its words in Segoe UI Variable Text, else Segoe UI, else
  the system's face. A font is named, never fetched: the page stays one file with no outside resource. The mode is
  the browser's unless the document's root names one, as before. Since 2026-11-11 the page's figures are in its
  words' family with tabular digits, as the window's are, and since 2026-11-12 its grid is the dark mode's alone
  (below).
- An account's card on the page shows its two windows as the window's card does: concentric rings, 64 pixels square,
  from the same geometry and in the same colours as the window's — the weekly window outside in the logo's blue, the
  5-hour window inside in its green, each arc taking the warning or the critical fill at those levels — beside the
  windows' names and figures, a dot of each ring's colour before its name, a figure at a level written in that
  level's text colour, and the plan under a hairline. No bar remains on a card. An account with no 5-hour limit draws
  one ring as thick as the two, and a window not started its track alone (since 2026-11-11 the page's rings take the
  window's thinner band, and the single ring is no thicker, below). The card of an account a client uses is
  edged in the account's colour, with a soft shadow of it. Since 2026-11-12 the card stands in the order of the
  window's card, and a strip of the account's colour inside its left edge marks the account in use, with no shadow
  (below).
- The page's cards say what the window's say, by the window's bounds: a reading's moment only once the reading may
  be out of date, once after the last response where both windows rest on one reading and on each window's line
  where they differ; a plan's days left only within a week of its renewal; and the line under a 5-hour window not
  started, *starts with the next message*, goes. A window never read says no moment. The subscriptions' table still
  says every plan's days left. Not taken: the page keeping every figure because it is read later than the window.
  Revisit should that be wanted.
- An account's share tile draws the share as a thin bar in the account's colour under its figure, from the share and
  the colour the history gives with the figure, as the History window does; every tile keeps the bar's room.
- A chart's line stands over the History window's shade and, in the dark mode, its glow, at that window's values
  (0.14 and 0.20; one stroke 2.8 times the line's width at 0.14), the shade under the gridlines; the columns carry
  neither. A chart's shades are named from everything they are drawn from, so two charts of one page never share a
  name.
- Glow is on data alone and in the dark mode alone: a soft shadow of its own colour on a ring's arc, and the wider
  stroke under a chart's line. Not taken: an SVG filter. Revisit should the glow not read on a display.
- One thing moves on the page: an arc at a warning or an error level pulses as the window's does, every 3.4 s down
  to 0.58 of its strength, and not at all where the browser asks for reduced motion.
- The recommendation stands on the window's band, and the page's edges are drawn in the cards' hairline; the
  palette's translucent `border`, which nothing then used, goes.
- No logo stands beside the page's title. Not taken: the logo drawn on the page, which would need a second drawing
  of it as SVG, or the service's package importing the window's. Revisit should it be wanted there: the drawing then
  moves to where both can reach it, as the rings' geometry did.
- What the page and the window share lives in the service's package, which imports nothing of the window's: the
  rings' geometry and their two colours, which the logo's drawing now takes from there too, the two bounds and the
  rule for saying one reading once, and the colours of the level texts, the recommendation's band, the hairline
  edge, a ring's track and the page grid, their values unchanged. Not taken: the page keeping copies of its own.
- The README's four pictures show the dark mode, the look's showcase. The release walk's picture run writes the dark
  theme into the window's own record before the window opens, as the Theme control (since 2026-11-11 the View menu's
  theme, below) would have left it, whatever
  mode Windows asks for, and checks that the window wears it. Not taken: setting Windows' own mode in the sandbox.
  Revisit should light pictures, or one of each, be wanted. The dark page ground is lighter than the dark band a
  capture's trimming cuts away, so no pixel of the window is lost to it.
- A width counted in digits takes a digit's real width, a fraction of a pixel, and is rounded up, where it took the
  width rounded to a whole pixel first. Measured on the development machine, 2026-11-10, with Qt 6.12.0: a digit of
  the default font is 6.47 pixels wide and 6 as a whole number, at device pixel ratios of 1.5, 2, 3 and 4, so a column of
  24 digits came out about 12 pixels narrow. Measured in Windows Sandbox the same day: at a display scale of 150 %
  the earlier count cut every period of the Bills and sources window's list and cells of the Conversations
  window's Last activity column; with the change every cell fits at 200 %, the one scale it was then run at.
  Revisit should a cell still be cut at 150 %.

The maintainer's decisions on Fable's weekly window (2026-11-10), built the same day:

- WindowTally shows a model's own allowance inside the weekly window, as claude.ai shows Fable's, on the band and in
  the window, and shows none on an account that has not used the model.
- It reads that window through the browser extension, after measuring in Chrome what claude.ai's page receives
  (*Sources*). Not taken: WindowTally asking claude.ai's usage itself with the account's sign-in, which would break the
  promise that no part of WindowTally reads a credential or sends a request; nor reading the copy of the last usage
  response Claude Code keeps in its own configuration, which Claude Code does not document.
- The two additions to the contracts, `weeklyScoped` in the browser reading and `scoped` on status.json's weekly
  window (*Contracts*), are the maintainer's decision: each an optional key, its version unchanged, checked or read on
  its own.
- The price of Fable 5.2, which the table lacked, so that every Fable 5.2 response from 2026-11-09 on was stored with
  no cost, is added in the same change, with the pricing of responses stored before their model had a price.

Choices made in building them (2026-11-10):

- A model's window is shown only where some reading of it in the last six weeks stood above nothing: claude.ai may
  list the window at 0 % for an account that has not used the model. Revisit should it be wanted always, or should
  claude.ai be seen to leave the window out for such an account, when its presence alone would decide.
- Between claude.ai's readings the window is carried forward by the model's part of the weekly window's measured rise,
  shared with every other model by what each spent at its own points per dollar, rather than by the model's cost at the
  account's single weekly points per dollar, which it was built on first: a reading is otherwise hours old while
  Claude Code's use goes on, and the plan meters families unevenly against their list prices. Measured on 2026-11-10
  and -11, over spans that began and ended at a known level of Fable's window — a reset of it or a claude.ai
  reading — a dollar of Fable 5.2 took several times the weekly points a dollar of the other families took. The
  single rate carried a reading far below claude.ai's, and then read the reset that followed as a fall it could not
  place, while the shared rise carries the same reading close to claude.ai's and reads the reset as one. Not taken: a
  single fixed ratio between families, which a change of the plan's metering would leave wrong.
  Revisit should estimates again be found far from the next reading, or should Claude Code come to hand its plugins
  the per-model window, which would then be read rather than estimated.
- Mythos counts with Fable, as the history already groups them, being Fable's counterpart for verified
  organizations. Revisit should claude.ai list a separate window for it.
- A fall of the weekly window giving back about the model's part of the week — within three points, or a quarter of
  that part, the part being an estimate — is a reset of its allowance; any other fall that could have touched it
  leaves the window unknown; a fall while the model held under three points of the week is not its own. Measured in
  the ledger the same day: twice the weekly window stood still once Fable's allowance filled, then fell by about the
  model's part of the week when the allowance was reset, its reset time unchanged. Revisit should a reset be seen to
  give back another amount.
- A per-model window warns at 80 % and 95 %, from status.json's figure, an estimate included, whenever a reading comes:
  the allowance fills within hours and past it the model costs usage credits. Not taken: the weekly window's 70 % and
  90 %, or no warning. Revisit should either be wanted.
- The weekly window's projection stops the model's part of its pace at the model's allowance, that part being the
  model family's share of the use over the projection's span, each family's cost at its own points per dollar: past
  the allowance the model's use stopped raising the week, as measured above. Revisit should claude.ai be found
  counting use at usage credits against the week.
- Per-model windows enter neither the recommendation nor the tray icon nor its tooltip, and the history page and the
  History window are unchanged: a full allowance does not stop an account, and the tooltip's 127 characters are the
  accounts'. Revisit should they be wanted there.
- The window's card holds one per-model block, the first window status.json gives, claude.ai listing one. Revisit
  should a second be seen.
- A model with no list price is named among the source problems, so the band's flag of source problems shows: a cost
  silently counted as nothing hid a day of Fable's. Revisit should the flag prove noisy for a model that will never be
  priced.
- The pricing of stored responses reads every response without a cost at each pass, counting them by model first and
  reading only those of a model the table now names; there are few such rows. Revisit should the pass's `prices`
  phase be measured slow.
- `model_family` and its table of families moved from `history` to `pricing`, since `limits` needs them and `history`
  imports `limits`.
- A per-model window's warning record counts as a new window only on a fall of 20 points or more: its figure is an
  estimate a claude.ai reading may lower by a few points, and a reset of the allowance gives back the whole of it
  (above). Revisit should a reset of an allowance be seen to leave its figure within 20 points
  of where it stood.
- A window's name maps to its family by the family's words, so "Fable 5.2" or "Claude Fable" count Fable's use and a
  name of no family counts none: claude.ai's label may gain a version. Revisit should a per-model window be named for
  something no family's words cover.

The maintainer's decisions on resets outside the schedule and what the plans covered (2026-11-11), built the same day:

- WindowTally kept no count of each account's resets outside the schedule, extra or Fable's, and the maintainer
  observed that without one a comparison of the plans with the API may read distorted; asked whether the multiple of
  the plans' cost should be given twice, with resets and without, for the user to compare, the maintainer decided it
  be built so (*Rules*, *What the plans covered*).
- The multiple without resets counts, per account and scheduled week, only the use up to the moment the week's points
  reach one full window, every reading's rise counted on from the first reading after a fall of three points or more,
  the dollars between the two readings across that moment split by points and the use between a reset and the first
  reading after it not counted, so the windfall is never overstated. The maintainer's decision.
- Use paid outside the plans — a Fable response while Fable's allowance stood full, by the live estimate's rule, which
  the proposal bounded to the weeks claude.ai has read Fable's window, from 2026-11-10, and any response while the
  weekly or 5-hour window stood exhausted — is left out of both multiples and of what a full window holds, and shown
  as a figure of its own; the live ≈ estimates are not changed. Proposed, approved.
- status.json's `thisMonth` gains two optional keys, its version and its other keys unchanged, so that the window's
  header and the `status` command give both multiples (*Contracts*). Proposed, approved.
- In which weeks a model's own allowance stands. As first built it stood in every week of an account once claude.ai
  had read the window on any account, the weeks before that first reading included, past the proposal's bound; offered
  that reach, the weeks claude.ai read the window alone, or every week from claude.ai's first reading of it on, read
  or not, the maintainer chose the last: before that first reading a model's use is the plans' and no fall is its
  reset (*What the plans covered*). Proposed, approved.
- Whether a reset outside the schedule is ever paid for, asked of the maintainer, who answered the same day: none is.
  Anthropic hands resets out at random, free and not for sale, and the user takes each when they choose, of the week or
  of Fable's allowance alike; only the week's own reset keeps its fixed time. The multiple with resets therefore counts
  no paid use, the room a reset made being a chance gift, which the multiple without resets leaves out (*What the
  plans covered*).

Choices made in building them (2026-11-11):

- A reset outside the schedule is of one of three kinds, *of a kind not known* among them: where the readings cannot
  decide, the table says so rather than call a Fable reset in a week claude.ai did not read Anthropic's. Revisit
  should two kinds be wanted.
- From claude.ai's first reading of a model's window on, an account's allowance for a week is the last claude.ai gave
  it by the week's end, else the first it gave after: the allowance is the plan's, half the week as read on Ultra,
  Fable 5 and 5.1 counting with Fable; an account with no reading of its own takes it as unknown. In the week that
  first reading falls in, the carry counts the model's use from the week's start, as the reading itself does. Revisit
  should a plan change be seen to change the allowance.
- Past weeks' points per dollar are the live figure's as they stood at each week's end, the rises of the 14 days
  before it, cut from one reading of the account's rises, a run counting only where something was spent across it
  within the cut: the plan's metering may change over time, and one reading per account keeps the split cheap.
  Revisit should the estimates be found far from the readings.
- A response's test of a full allowance takes in the falls its own weekly reading shows, the first at or after it: a
  fall that reading shows came before the response, and left out, the first response after a reset of Fable's
  allowance would count as outside the plans.
- The use beyond one window starts only once the count passes 100: a week at exactly 100 has used one window, and a
  reading trailing after it would otherwise mark the week's later use beyond.
- What a full window holds leaves out both kinds of use outside the plans, whichever window a step is of: a step of
  the weekly window can bracket responses made while the 5-hour window stood exhausted, and the reverse. The proposal
  had said the exhausted windows' use was left out already, which held within one window only.
- The weekly chart's marks are a disc for an extra reset, as before, a diamond for a model's allowance and a square for
  a kind not known, the two squares of the disc's area, so no kind reads larger; the legend outlines each in the
  quieter ink, the first saying the marks wear the account's colour.
- *Resets outside the schedule* stands after the weekly chart and its use by product, on the page, in the export and
  in the window, always, *None.* where the range holds no reset, in the tables' settled form. Revisit should the
  maintainer take a new section for a change of the page's layout, which is then sketched first.
- The caption `API-equivalent ÷ plans` stays, though the figure now counts the use the plans covered, the part outside
  them standing beside it: it is the figure most looked at. Revisit on the maintainer's word.
- The multiple without resets stands — the summary's tile, the month's line, a plan period's cell — only where it
  reads differently from the one with resets: equal, it says nothing new, and the section's hint says when it shows.
  The proposal had shown both always. Revisit should both be wanted always.
- The keys are `inPlans` and `withinOneWindow`, each written only where it is less than the sum before it, so a month
  with no extra usage and no reset writes status.json as before.
- A plan period's split is computed only where the history is drawn — the page once per render, every ten minutes,
  from the earliest recorded plan period on — never in the pass's billing report, which runs every pass: its cost grows
  with the span. The month's split runs in the status phase of every pass, and a failure there leaves status.json
  without the two keys and names the source problem, as the use by product does.
- The history carries a model's window by the live figure's own code, `limits.ScopedCarry`, taken out of the live
  figure with no change of its result, so the two cannot part; `tests/test_scoped_windows.py` binds the live figure
  unchanged.

The maintainer's decisions on keeping the computer awake (2026-11-09 and 2026-11-11), built on 2026-11-11:

- WindowTally keeps the machine awake while a turn of any Claude Code session is in progress, the desktop app's or a
  terminal's alike, and holds nothing for a session waiting idle; the ledger service holds it, so it stands with the
  window closed (2026-11-09).
- It holds on battery power as on mains (2026-11-11).
- The user can turn it off: a switch beside *Silence notifications* in the window's View menu and its tray menu, on by
  default, kept as a new key of `settings.json`, version 1 (2026-11-11).
- The window's count of the desktop app's sessions at work moves onto the same source as the keep-awake (2026-11-11).

Choices made in building it (2026-11-11):

- The source is Claude Code's own session registry, not the plugin's markers: it names the desktop app's sessions and
  a scripted run's, and by the CLI's binary a terminal's, it showed a turn at work that the markers missed (*Sources*), it is the status
  Claude Code's own sleep inhibitor follows, and a file naming its process tells a dead session at once. The plugin,
  the markers and status.json's contract are unchanged; since 2026-11-15 the markers are withdrawn (below). Revisit
  should a terminal's turn or a scripted run be found not shown `busy`.
- At work is Claude Code's `busy`: a turn running, or work it delegated still running. `waiting` (a permission prompt,
  a question), `idle` and `shell` hold nothing. Revisit should a session stopped at a permission prompt, or a
  background shell, be wanted kept awake.
- A session counts only while its process lives and is the one that wrote the file — its id, created at the file's
  FILETIME — with no time limit, Claude Code renewing no busy status while a turn runs. Revisit should a live process be
  found stuck `busy`. The registry's `pidDomain` is not read: a process id with its exact creation time matches no
  other machine's process. Revisit should a registry shared between machines be seen.
- The system is kept awake, not the display, through one `PowerCreateRequest` set for the system and for execution:
  execution is the kind the desktop app's own request takes, and Windows takes it for the system on a computer that
  sleeps to S3. Revisit should a computer with modern standby be found to suspend Claude Code with the screen off while
  the request stands.
- The keep-awake looks every two seconds on a thread of its own rather than waiting on the folder's changes: a look
  reads a few small files and opens one process each, and meets "within seconds" whatever a pass is doing. Revisit
  should a look be measured to cost noticeable time.
- The key is `keepAwakeOff`, written only while true: a key added without a change of version names the state its
  absence is not, as `silenceNotifications` does. Settings that cannot be read keep the computer awake, the default.
- A file with no status yet is a live session not at work and no problem, since a process writes its file a moment
  before its first report; a file whose process is gone counts as none and is no problem, Claude Code removing its
  file at its end and a crash leaving one. A status the reader does not know counts as not at work and is named:
  counted as work, it could hold the computer awake for a status that means anything.
- The window's check whether the ledger is behind a session reads "a session of the app at work now, or one whose
  status changed after the pass": the markers it replaces were rewritten every 15 s through a turn, while a status
  changes only at a turn's start and end.
- `markers.count_working_sessions` and `working_session_ids` stay as the markers' reading, which their tests bind and a
  program outside WindowTally follows; the reading of the markers' latest write, which nothing calls any more, went.
  Since 2026-11-15 the markers are withdrawn, with their reading (below).

The maintainer's decisions on what a session ran with and on the switch dialog's search (2026-11-11), built the same
day:

- The desktop app, opening a session another account ran, takes its model and permission mode from its transcript's
  last lines, the settings' default mode where those name none, and its effort from nothing (read in its program,
  desktop app 4.23118.1.0, 2026-11-11). Offered a resume command that goes on at the session's last effort and
  permission mode, and the lists showing both on the desktop app's path for the user to set them again, the
  maintainer chose both.
- The switch's dialog takes a search by title, above the list with the count beside it, as sketched; approved.
- The ledger records each main session's last permission mode in a table of its own, `session_modes`, which `open`
  creates without a change of version, as it adds facts no other figure rests on, and the transcripts already read
  are read once more for it; recommended and approved.

Choices made in building them (2026-11-11):

- A session's effort is its latest main answer's, a subagent's left out: the latest answer carries the session's
  setting as it stands. Every main answer in the development machine's ledger names an effort
  (measured 2026-11-11). Revisit should Claude Code write answers without an effort for a model that keeps the
  session's.
- A mode is shown in the desktop app's own words — *Manual*, *Accept edits*, *Plan*, *Auto*, *Bypass permissions*,
  *Don't ask* — and `manual`, the CLI's later name for the default, as *Manual*; another word of letters alone, of at
  most 32, as written, and anything else not at all, an effort under the same check. Revisit should the app rename a
  mode.
- The resume command passes the default mode as the transcript names it, `default` or `manual`: left out, a setting
  naming another default mode would change the mode the session goes on in, while a CLI that refuses the value says
  so. Claude Code 2.1.310 lists `manual`, takes `default` unlisted and refuses a value it does not take with an error
  (measured on the development machine, 2026-11-11). Revisit, to `manual` alone, should a later CLI refuse `default`.
- A bypass is passed as `acceptEdits`, as the desktop app lowers it on taking a session in (read in its program,
  4.23118.1.0). Revisit on the maintainer's word.
- *Ran with* stands last in both lists, where the sketch showed it before Last activity: the columns before it keep
  their places. Revisit on the maintainer's word.
- The dialog's search matches as the Conversations window's does, and a session it hides keeps its tick and is
  carried, the count of the ticked keeping it in sight: a search narrows what is looked at, not what is taken along.
- What a session ran with is read by the service from the transcripts it reads already, not by the window from a
  transcript's last lines when a list opens: those lines need not name a mode, the desktop app's own adoption then
  falling back to the settings' default, and the window reads no transcript. Not taken: a reading on demand.
- The switch's dialog holds its list at the height the list asks for, its heading and every row it asks to show, at
  least two and at most eight (`CARRY_ROWS`): opened at the height its layout gives for its width
  (`common_view.size_to_content`), the dialog falls a row or more short of what the layout asks for, which the list
  alone would give up. The hold is the dialog's own, not a change to the sizing it shares with the question dialogs,
  the About window, the Arrange accounts window and the Bills and sources window: measured on the development
  machine, 2026-11-11, on Windows' own platform with no window shown, the Arrange accounts window shows every account
  whole, one to nine, and the dialog every session whole, one to eight, one of them working. Revisit should another
  window that sizing opens be found cutting its list.

The maintainer's decision on the cost by context (2026-11-11), built the same day:

- WindowTally helps a user see whether their way of working needs changing with figures, not advice: one section on the
  history page and in the History window, the cost by the size of a request's context, with its sessions and the cost
  per response, and a line counting the responses that wrote their context to the cache again after a pause. No
  estimate is needed — of cache reads from the average price per token, for instance — the ledger recording every
  response's cache reads and its writes at both lifetimes.

Choices made in building it (2026-11-11):

- The table counts every account together, where sessions, models and effort go per account: how long a context grows
  is a matter of how the user works, not of an account, and per account would multiply its rows. Revisit should it be
  wanted per account.
- The ranges end at 100K, 200K and 500K tokens: 200K is the standard context window's edge, with models of 1M above
  it, and the development machine's requests reached all four (measured 2026-11-11). A range is half-open, a request
  at an edge standing in the range above it, and its words name no price tier. Revisit on other edges.
- A rewrite is a priced response that came longer after the previous response of its own session or subagent within
  the range than the cache it writes lives — an hour where it writes to the 1-hour cache, else five minutes — wrote
  more to the cache than it read, and read less than the previous request's context. What it cost is what writing that
  context again, less what was read and at most what was written, cost beyond reading it from the cache, split between
  the two lifetimes as the response's own writes are, at the tier its whole context puts it in: a live cache would
  have served the earlier context, while the turn's new tokens are written either way. A stream's first response in
  the range is never judged; a change of model after a pause counts too; and the previous request's output, which also
  enters the next prompt, is not counted as cached, so the figure errs low. Not taken: a pause of five minutes for
  every response, which counts a 1-hour cache still alive, as a compaction after a pause writes more than it reads;
  and a premium on every token written, which prices the turn's new tokens too. Revisit should a case be measured where
  the rule misjudges by much.
- The section stands after the effort table, inside the usage tables, on the page, in the export and in the window, in
  the tables' settled form — a heading with its hint, the table with its *In all* row in bold, the rewrites as a note
  beneath. Revisit should the maintainer take it for a change of the page's layout, which is then sketched first.
- The section reads the range three times, its *In all* sessions counted afresh, since a session spans ranges and
  accounts, once each time the page is written, every ten minutes, and off the window's thread. Revisit should it be
  measured to slow a pass.

The maintainer's decisions on the main window's card and header (2026-11-10 and 2026-11-11), built on 2026-11-11:

- The main window takes the ring cards tightened, every word kept (2026-11-10): a card narrows so that more stand
  abreast in a window of a given width, and holds the fullest case — an account with a 5-hour window, the weekly
  window and a per-model weekly window together — its two rings, thinner, beside the 5-hour and the weekly figure, the
  per-model window as a thin bar under them, then each window's reset, the pace and the week's use by product, and the
  plan under a hairline. Not taken: one compact row per account; the account in use as a panel and the others as
  rows. The decisions that every word stays shown and that the rings are the two windows' gauges stand.
- The five actions — Refresh now, Conversations, History, Bills, Data folder — stand at the right end of the header's
  line, and the theme and Keep on top are set in the View menu alone, the row at the window's foot going with its
  caption, its drop-down and its check box (2026-11-11).

Choices made in building them (2026-11-11):

- The card, from the top: the title row and the heading as before; the two rings, centred beside the two windows'
  rows — a dot of each ring's colour, the window's name, its figure — and spanning those two rows alone, so a window
  with nothing more to say leaves no gap; under them the per-model window's row, its name, its figure and its bar
  across the card; then each window's line across the card's whole width — when it resets, the pace, the reading where
  it is said, on the weekly window its use by product, then the per-model window's words — behind the key of its
  gauge, a dot for a ring and a short pill for the bar, the key's place kept empty where a window has no gauge, as the
  5-hour window of an account with no 5-hour limit has none; and the plan under a hairline. The card's margins are
  three quarters of a line at its sides and half a line above and below. Revisit should the keys read as clutter.
- The rings: a band of 0.08 of the square's side, the gap and the glow's margin as they were, the square 3.2 lines of
  the default font, the height of the two windows' rows. An account with no 5-hour limit draws its weekly ring alone,
  in the weekly ring's own place and band, so no empty ring reads as a window at zero and no ring stands thicker than
  another. The history page's rings are drawn from the same geometry; the tray icon and the logo draw their own and are
  unchanged, the tray's single ring as thick as the two.
- A per-model window's bar is filled from the left as far as the window is used, never shorter than it is tall once
  anything is used, on the rings' track colour, in the weekly ring's colour at rest and in the warning or the critical
  fill at those levels, the window lying inside the week. A window whose figure is unknown fills nothing, and its
  track is drawn as dashes, so it never reads as a window with nothing used. The bar never moves.
- The account in use is marked by a strip of its colour inside the card's left edge, a fifth of a line wide and at
  least 3 pixels, its ends following the card's rounded corners. No card glows, in either mode, and a card's edge stays
  its hairline under the pointer, a card answering no click. Revisit should a glow be wanted back in the dark mode.
- Every chip — `desktop app`, `CLI`, `use next` — wears one neutral tint, `#e6ebf2` in the light mode and `#1c2a3d` in
  the dark, its ink at 4.5:1 or more on it and the tint apart from the card, which the suite measures.
- Push buttons and segments wear one quiet form: the control face under the hairline edge, rounded by 5 pixels, padded
  2 pixels by 10; the filled form stays a view's one primary action, on the main window the recommended account's
  first switch button (since 2026-11-12 that button alone, below). The words on each face, the hover and the pressed one, stand at 4.5:1 or more and a disabled
  word at 3:1 on the face, in both modes, which the suite measures.
- Figures are set in the words' family, Segoe UI Variable Text, else Segoe UI, semibold, with the font's tabular
  digits (OpenType `tnum`), and the history page's figures in its words' face with tabular digits likewise. Measured
  with Qt 6.12.0 on the development machine, 2026-11-11: Segoe UI Variable Text's ten digits share one advance with
  tabular digits and take two without them; Segoe UI keeps two advances either way, so where Segoe UI Variable is
  missing a changing figure can shift what follows it. Revisit should that be seen.
- The page ground under the main window and the History, Bills and sources and Conversations windows lays its fine
  grid in the dark mode alone; the light mode's pale page stands on its own. The page's colours are unchanged, and the
  history page's ground keeps its grid in both modes (since 2026-11-12 in the dark mode alone too, below).
- A card's least width is 22 lines of the default font: measured on the development machine at display scales of
  150 % and 100 %, 2026-11-11, the least at which no word of a card's title row — a name of eight letters and its two
  switch buttons — is cut and each window's line of its usual length stays on one row; at 21 lines the name was cut
  by a few pixels. The window opens 70 by 30 lines: three cards abreast with the vertical scroll bar showing, the fullest card
  whole and two lines to spare, where at 68 the scroll bar narrows the view below three cards; it opened 68 by 40 with
  two abreast. The window's least width is under 28 lines, where it was 46. Revisit should a word be cut at 100 % or 200 %.
- The actions stand beside the header's words while the room left of them holds the words' widest piece, so the
  words wrap only between their pieces; else on a row of their own under the words, at its right end. Where they stand
  is measured again only when the words or the window's width change, the header being rewritten every second.
- A card line whose first piece is wider than the card has a line of its own, where its words wrap, and every piece
  after it a line of its own: such a piece was cut at the card's edge.
- Every word, figure and action is as it was, and so are status.json, `settings.json` and `window.json`, the theme
  and Keep on top keeping their places in `window.json`. Measured on the development machine, 2026-11-11, on an
  invented machine in the dark mode, 70 by 40 lines, nothing near a warning, over 120 s, three runs each: the window's
  processor time at rest 0.56 %, 2.25 % and 1.61 %, against 1.12 %, 3.74 % and 4.10 % before; nothing new runs on a
  timer.

Choices made in carrying the tightened look into the other windows (2026-11-12):

- The filled button is the main window's recommended switch alone: Arrange accounts' OK and the Bills and sources
  form's Record wear the quiet form, OK still the answer Return gives. Not taken: each window's one primary action
  filled, as the look held until then. Revisit should a window's main action be lost among its others.
- A list given whatever height its window leaves it — the Conversations window's, and the Bills and sources window's
  list of bills — stands as tall as a whole number of its rows, the rest of the height empty under it, so its last row
  is never cut through its words; it scrolls by rows, so each step ends on a whole one too. Its height is worked out
  again when the window is resized, a column dragged, the first rows come into an empty list, or the list's style, font
  or display scale changes, and which scroll bars it shows is worked out as Qt shows them, each of the two able to make
  the other needed. The other lists ask for a number of rows and stand at it. Measured on the development machine,
  2026-11-12, on an invented machine: 9 pixels of a cut row stood under the Conversations list's last whole row and 4
  under the bills', none since.
- The row the keyboard is on is marked, while its list has the focus, by a rounded strip of the focus colour at the
  left of its first cell, 0.15 of a line wide and at least 2 pixels, standing 0.15 of a line in from the row's top and
  bottom; the row keeps the selection's tint across its width. Windows 11's style framed that row in the text colour,
  which in the dark mode read as a harsh white box: a cell is now drawn without its focus state, so the style draws no
  frame. The strip stands at 3:1 or more on a row's field, hover and selection in both modes, which the suite
  measures. Not taken: a style-sheet rule with no outline on the list, which left the frame standing (measured with Qt
  6.12.0 on the development machine, 2026-11-12). The strip shares the focus colour with a ticked box beside it.
  Revisit should the two run together, or the mark not be seen.
- The History window's shade under a run of readings — a line breaks where readings stop for twelve hours — fades
  from the run's highest point to nothing at the run's own lowest point, or further down by at most twice the run's
  width, and never past the baseline. A run that stops within hours of starting is a few pixels wide over thirty days;
  shaded to the baseline it stood under its line as a thin column of its own. A wide run, and one that drops to the
  baseline at a reset, still fades at the baseline. Not taken: no shade under a short run, which would make a cliff at
  whatever width was chosen. The history page's charts still shade every run to the baseline (since 2026-11-12 by
  this rule, below). Revisit should a short run's shade read as too shallow.
- The other windows stand at the main window's density. The History window's tiles and the Bills and sources form
  wear a card's padding, three quarters of a line at the sides and half a line above and below, and the tiles stand
  half a line apart, as the cards do, where they stood a line apart; the History window's head has half a line above
  it and each section's heading after the first a line, where they had a line and a line and a half; the
  Conversations and Bills and
  sources windows stand half a line in from their tops and feet, where they stood a line; Arrange accounts, About, the
  questions before a switch and the sessions a switch carries stand a line in from their edges, where they stood a
  line and a half; the window of text holds half a line between its text and its button, where it held a line; and a
  menu's items, the tray's and the window's alike, are padded 4 pixels by 18, 24 at the left, where they were padded
  5 by 22 and 26.
- A dialog fixed to its layout's height holds its paragraphs at one width, each as tall as its words at that width:
  the layout asked a paragraph its height at the column's width, which is wider, so it counted one line a paragraph
  and the sessions a switch carries came out too short, the list standing over the note under it (seen on 2026-11-12,
  since the list's *Ran with* column widened it on 2026-11-11). A paragraph is measured in the font its style gives it;
  one a change of display scale reflows while the dialog is open is not measured again. About's lines are held the
  same way and showed no clipping; they are as they were.
- The History window's share bar and the card's per-model bar stay two drawings: one shows a share, the other a
  window whose figure may be unknown, drawn as a dashed track. Revisit should they come to draw the same thing.
- Every word, figure, action and window's regions are as they were. Measured on the development machine, 2026-11-12,
  on an invented machine in the dark mode, the History window open, over 60 s, three runs each: the window's
  processor time at rest 0.13 %, 0.03 % and 0.10 %, against 0.03 %, 0.00 % and 0.05 % before; nothing new runs on a
  timer, a list being placed again after a change of its style, font or display scale once the change has settled.

Choices made in carrying the tightened look onto the history page (2026-11-12), the History window's export with it:

- An account's card on the page stands in the order of the window's card: its name and roles; its last response and,
  where both windows rest on one reading that may be out of date, that reading's moment; the rings beside the two
  windows' rows — a dot of the ring's colour, the window's name, its figure; then each window's line across the card
  behind its ring's dot — when it resets, the pace, the reading's moment where the two windows were read apart — the
  weekly window's line followed by the week's use by product on a line of its own, the dot's place kept empty; and the
  plan under a hairline. Every word the card said it still says. The page still shows no per-model window, which the
  window's card alone does. Not taken: the use by product joined onto the weekly window's line, which would add a
  joiner the page never wrote. Revisit should it be wanted on that line.
- An account with no 5-hour limit puts its weekly window first; beside the rings its 5-hour window says *no limit*,
  the dot's place empty, and *this account has no 5-hour limit* stands on the window's line, as the window's card
  puts the name and *no limit* alone beside the gauges. Not taken: the sentence beside the figure. Revisit should it be
  wanted there.
- The account in use is marked by a strip of its colour, 4 pixels wide, inside the card's left edge, clipped to the
  card's rounded corners: a fifth of the page's line of about 20 pixels, as the window's strip is a fifth of its
  line. The card's edge stays the hairline and it casts no shadow. Revisit with the window's strip.
- The page ground lays its fine grid in the dark mode alone, as the window's ground does; the light mode's page stands
  on its own. The palette's colours are unchanged.
- The page stands at the window's density, its line 14 pixels at 1.45, about 20: a card's, a panel's and a tile's
  padding is 10 pixels above and below and 15 at the sides, where a card and a panel had 14 and 16 and a tile 10 and
  16; cards and tiles stand 10 pixels apart, where 12; a section's heading has 20 pixels above it, where 32; the line
  under the title 10 under it, where 16; the recommendation 10 above it, where 12; the page stands 10 pixels in from
  its top, 15 from its sides and 40 from its foot, where 24, 16 and 48; a table's first and last cells 15 pixels in
  from its sides, where 16. Inside a card, the title stands 2 pixels over the line under it, where 8.
- The cards keep their width, at least 280 pixels: within the page's 1000 pixels three stand abreast, and four would
  need cards of about 240, where a weekly window's line wraps onto a third line. The page is tightened by its order,
  spacing and padding. Revisit should four abreast be wanted.
- A chart's shade under a run of a line fades from the run's highest point to the run's floor by the rule the History
  window shades by (2026-11-12, above), which lives in the service's package beside the charts' other shared values,
  the window taking it from there: the service's package imports nothing of the window's. Each run has a gradient of
  its own, its floor its own; a run whose floor stands no lower than its top, a level run on the baseline among them,
  is not shaded, in the window as on the page. Not taken: runs of one top and one floor sharing a gradient, which
  saves a few hundred bytes for a key of its own. Revisit should a page's size be felt.

Choices made in making the README's pictures again (2026-11-12):

- The pictures stay dark, the look's showcase, and the main window's picture shows one account in the fullest case: a
  5-hour window, the weekly window and a per-model weekly window. The release walk's seed writes claude.ai's own
  reading of Work as the browser extension's host writes one, a minute after Work's last reading, with that reading's
  5-hour and weekly figures and Fable's weekly window at 34 % of an allowance of half the week, resetting with the
  week; the walk checks that Work's card shows it. The figure is invented, mid-range and short of every warning, so
  the bar reads plainly; Work's seeded sessions use no Fable, so the window stands at its reading. Revisit should
  another figure, or a picture without it, be wanted.
- They were made in Windows Sandbox from an unpublished release, `2026.11.90`, built without its suite from a
  throwaway repository holding the tree's WindowTally folder. Which account the
  window names to use next turns on the day of the week the pictures are made: on this Thursday it names Work,
  already in use.

The maintainer's decisions on the history's sections of one kind (2026-11-12), built the same day:

- The History page's tables of one kind are merged, one switch in place of two tables: the token tables by week and by
  month; what a full window held by plan and by week; and the cost chart and the token chart, on the same columns —
  each section's heading followed by a segmented switch, the chart section's words and hint changing with the view,
  each account's cost by model family staying cost-only beneath it — in the History window and in the exported HTML,
  as sketched. Not taken: the models and effort tables merged.
- This amends the decisions of 2026-10-28 (what a full window holds, by plan and week by week, under two headings) and
  of 2026-11-02 (a token chart, then a table by week and a table by month), and the headings listed among the words
  shortened on 2026-11-04: `Tokens per day`, `Full window, by plan` and `Full window, by week` now stand inside their
  switches, the token tables' heading reading `Tokens by` and the capacity's `Full window, by` before the switch.

Choices made in building them (2026-11-12):

- A view's heading is its own: the words before the switch and the view's hint, the switch's word completing the token
  tables' and the capacity's headings, the chart section's words changing with the view, since its titles and hints
  differ by view. Revisit should fixed headings be wanted.
- Each switch opens on its first view — the cost; by plan — and the token tables by week, but by month where the
  charts' columns are weeks, over 6 months and all, whose weeks outnumber the twelve rows a table shows before it
  scrolls; the history page, over thirty days, opens by week. Revisit on the maintainer's preference.
- A choice stays while the History window stands, through every change of span and Recompute, and is written to no
  setting, a view being no policy. Revisit should it be wanted remembered across starts.
- The export holds every view and opens at the window's choices; the page's switch is a radio button per view, unseen
  but reached by Tab and moved by the arrow keys, with labels in each view's heading, and the style sheet shows the
  checked view: no script. The history page the service writes carries the same three switches, sharing the export's
  sections, its token tables' range words after the switch.
- The page's filled label takes the palette's `advice` fill with a `baseline` edge and its focus ring `series-1`, the
  window's focus colour in both modes, the palette having no selection or focus colour of its own. Revisit on another
  look.
- The window lays out every view once and hides the others, so a view chosen again comes back as it was left, a table
  scrolled where it stood; one heading row builds plain and switched headings alike, and every chart's value labels,
  those of every view, set where each chart's axis stands, so an axis does not move with the view.

The maintainer's decisions on the band's windows (2026-11-14), built the same day:

- An account with no 5-hour limit shows no 5-hour window on the band: the terminal's line, the desktop's line of the
  account in use, the other accounts' line, the folded line and the card the fold button reveals drop `5h no limit` and
  the compact `5h none`, and its weekly window leads as before, on the in-use line at the 5-hour window's place and
  scale. This amends the words and drawings chosen on 2026-10-31 for the band alone: the panel, the window, the tray
  and the `status` command still say the account has no 5-hour limit.
- On the band a per-model window, Fable's, shows its figure alone, `Fable ≈2%`, in its warning colours and with any
  reset it shows, and draws no meter; the desktop's line of the account in use was the one place the band drew one. The
  5-hour and weekly windows keep their meters, and the panel keeps the per-model window's.

Choices made in reading a model's points per dollar off claude.ai's readings of its window (2026-11-14), the first
the maintainer's decision:

- The model family's points per dollar is read off claude.ai's readings of the model's own window wherever they
  measure it, and then stands in place of what the weekly window's steps leave once the other families' rate is taken
  out, which it was built on first (2026-11-10); the other families' rate is the steps' as before. What the window
  rose between two readings is the model's part of the week itself, while the remainder carries the other families'
  rate's error whole and leans low where the allowance stood full; the two are not pooled, one being measured and the
  other derived. Measured on the development machine, 2026-11-14: the remainder carried an account a few points of the
  allowance below the desktop app's figure, its two rates giving the week's whole rise right and splitting it wrongly;
  the read rate stood at times well above the remainder and at times level with it; and with each reading predicted
  from the one before it, the read rate took the error's lean to under a third of the remainder's and the error's
  size a little lower. A week in which claude.ai has not yet been read is still carried by rates measured earlier, as
  that account's was; its first reading sets the figure and measures the rate from the week's start. This answers the
  revisit of 2026-11-10, estimates found far from the next reading. Revisit should the read rate be found less steady
  than the remainder over long spans.
- No bound is set on the time between two readings of the model's window, unlike the three hours between the weekly
  window's: readings come only while claude.ai is open, and under that bound one of the three accounts had any
  evidence. Revisit should an account's read rate be seen far above its remainder with chat use of the model between
  its readings.
- Two readings across which the family spent nothing here measure nothing, as a run of steps with no dollars does
  not: the ledger held readings rising with no spend here, the model's use elsewhere, and counting them raised one
  account's rate.
- A week's first reading is measured from the week's start only where the window was read in an earlier week and the
  weekly window was observed by that start: a ledger begun mid-week, or a window that first existed mid-week, would
  otherwise count a week's points over part of its dollars. Revisit should the ledger be seen to miss an account's use
  after such a start.
- A fall of the weekly window leaves two readings unmeasured wherever the stretch between the weekly observation
  that showed it and the one before it overlaps theirs, the reset having come somewhere in that stretch; and a
  reading within a minute of its week's start is passed over, by the margin the windows' other readers keep.
- The history measures a past week's rates as the live figure would have, through the same rule
  (`limits.family_rates_of`), by the model's readings up to that week's end. Measured the same day while a suite ran
  beside it: the history's split over 6 weeks took 1.99 s where it took 1.85 s, over 26 weeks 2.12 s for 2.08 s, and
  the per-model standings of three accounts 1.41 s for 1.16 s.

Choices made in placing the lines of accounts whose plan has ended (2026-11-14), at the maintainer's word that the
line's switch button stood oddly far off:

- The window's line of an account whose plan has ended and that no client uses is one column wide, the lines standing
  abreast as the cards do, from the first column on the row after the last card's; it was across every column
  (2026-11-04), which at two columns or more put its switch button at the window's far edge, apart from its words and
  from every card's button. A line's button now ends where the button of the card above it ends. With no card at all,
  the lines take the columns the cards would, so none spans the whole width; each line keeps its own height at the top
  of its row, a line beside one whose words wrap never stretched to match it. Still a line under the cards, as the
  maintainer decided on 2026-11-04, never in a cell a short last row of cards leaves empty, which would make it the
  small card among the cards not taken then. Revisit should several such lines abreast be found harder to read than
  one under another.

The maintainer's decision on the session markers (2026-11-15), built the same day:

- The plugin no longer writes session markers, and the service no longer prunes them; the contract, session markers
  v1, is withdrawn. No part of WindowTally had read them since 2026-11-11, Claude Code's session registry standing in
  for them (*Sources*), and they could not serve another program's question either: a marker was renewed through a
  turn waiting for a permission or an answer just as through one at work. A program on the machine that wants to know
  which Claude Code sessions are at work reads Claude Code's own session registry, whose status tells a turn at work
  (`busy`) from one waiting on the person (`waiting`).

Choices made in building it (2026-11-15):

- The plugin no longer observes a turn's start or a session's end, which served the markers alone.
- Whether the desktop app hosts a session, which sets apart the account the band, the panel and the limit warnings
  judge by, stays as it was, in `plugin/hooks/hosting.ts` (*Rules*, *The band*).
- The service's reading of the sync's two switches and of the stored desktop logins, which shared the markers' module,
  is `windowtally/sync_store.py`, unchanged.
- A markers folder an earlier version left in the data folder is not removed, nothing reading it; it may be deleted
  by hand. Revisit should it be wanted removed by the service.

## Caveats

- Chat-tab conversations leave no local token record; they show only in the percentages.
- Until the plugin or the browser extension has written a reading for an account, that account's reset times are
  inferred and can be off by hours; the first reading replaces them.
- The browser extension relies on claude.ai's page asking for its usage, a request the site does not offer as an
  interface: should its path or its response's shape change, the extension reads nothing and says nothing, and
  WindowTally goes on as without it. A reading arrives only when the page itself asks, so between two of the page's
  requests an account used in a browser stands as last read, and its use by product is as old as the page's last
  request, which every surface showing it says. Should only the use by product change shape, the windows still arrive
  and the use by product is left out, and so with the per-model windows. Without the extension, chat on claude.ai in a
  browser shows only once the desktop app or Claude Code next reads the account.
- A per-model window (Fable's) reaches WindowTally only through the browser extension, so without it, or while
  claude.ai's page has not asked for its usage since the model was first used, no such window is shown. Between two
  readings its figure is an estimate from the model's API-equivalent cost on this machine, so use of the model
  elsewhere — claude.ai, another device — is not in it until the next reading; and a reset of the allowance is read
  from a fall of the weekly window, so a fall that does not match the model's part of the week — a reset of the
  allowance and another of the week at once, or an estimate far off — leaves the window unknown until claude.ai is
  read again.
- `install.ps1 -Mode Status` reads the host's key in the registry of the process it runs in, which from a terminal
  inside the desktop app may be the app's private view rather than the one Chrome reads.
- A window's figure is the highest of its observations, and the desktop app samples about every 15 minutes, reading
  a point above Claude Code a third of the time in the 5-hour window and half the time in the weekly one (measured on
  the development machine, 2026-10-28): while
  Claude Code's readings rise past the app's last sample, the figure is Claude Code's, and can stand a point below
  the app's own until the app's next sample.
- The ledger is the only lasting copy of expired sources: a schema change migrates it, never rebuilds it
  (`ledger.SCHEMA_VERSION`). A table that only adds facts no other figure rests on — `product_shares`,
  `scoped_windows`, `session_titles`, `session_modes`, `limit_stops`, `background_tasks` — is created by `open`
  without a change of
  version, so a ledger
  it was added to
  still opens in code that predates it, which never reads it; a reader that does read one asks whether it exists
  first, the window reading a ledger no pass of this code may have opened yet.
- A session's title has no time in its transcript, so the ledger keeps the one read last, the title the desktop app
  shows standing before the one Claude Code makes up itself; a `permission-mode` line has none either, so a session's
  mode is the one its main transcript names last.
- The desktop app's resume link, through which the window opens a session taken along at a switch and one the
  Conversations window opens, is no interface the app documents: an update can change it, and a session opened
  through it loses its effort and may fall back to the default permission mode, which the window says at every switch
  that takes one along and for every session it hands over whose effort or mode it knows, the switch's dialog and the
  Conversations window showing what each session last ran with. Whether the app took a link is not known to the window, only whether the shell could
  hand it on. It was measured adopting sessions the app's Code tab ran, so the Conversations window hands it no session the CLI
  alone ran, which opens with its resume command only.
- The resume command of a session whose folder is gone runs wherever the user starts it, Claude Code finding the
  session by its id beyond the current folder (Claude Code 2.1.310); a build that stops looking beyond it would not
  find the session there.
- A conversation the desktop app went on with in a new transcript stands in the Conversations window as two sessions:
  no transcript line joins the two, only the app's cards, which the window does not read.
- The plugin is built on Claude Code's early-access function-hook API, and the desktop app runs a Claude Code
  build of its own beside the CLI's (2.1.299 and 2.1.302 on 2026-10-21): a change to the plugin is validated
  (`claude plugin validate --strict`) and tested (`claude plugin test`) under both builds.
- Two sessions on one account crossing the same threshold in the same instant both warn: the plugin store has no
  compare-and-set, so each session writes back only the entries it changed, onto the store as it then stands.
- The plugin's tests (`plugin/tests/`) drive its hooks through Claude Code's test kit, which stands in for the
  engine and the display, and for Task Scheduler and the window behind the panel's window button; what the desktop
  app actually draws — the band's and the panel's sizes and meters, and the panel's names in one width, among it — and
  the window the button brings up, are checked by eye.
- The desktop app's screen of a new Code session has no band: the app starts the session, and with it the Claude Code
  process the plugin runs in, when the first message is sent, its focused session being none until then (its log,
  read on 2026-10-26). Before the first message the WindowTally window and its tray tooltip show the standings.
- What WindowTally says of a subscription is only as complete as the bills recorded: a bill not yet recorded shows as a
  gap, or as no plan today.
- A period's API-equivalent use counts only the responses the ledger attributes to the account, so a period before
  the ledger's record of the account began shows none.
- What a plan's full window holds is counted as though all of an account's use were Claude Code on this machine: the
  readings rise with the account's Chat-tab, browser and other-device use too, which costs nothing here, so wherever
  an account is also used otherwise the figure is a lower bound. Both surfaces say so above the figures.
- The measure knows an account's plan only from the bills: an account with no bills recorded is not measured, and the
  day a plan begins or changes is left out, a bill giving that day but not its hour.
- The renewal reminder is off by default: nothing on the machine says whether a subscription renews by itself.
- The profile's plan vocabulary is Claude Code's; a plan or tier it adds is one WindowTally does not compare until it
  learns it.
- The window's tray icon and notifications are Qt's (`QSystemTrayIcon`), and on Windows a notification needs the
  icon, so a window whose icon could not be made raises none, and says so, its notifications going to the status
  line. Qt reports nothing when Windows does not hold its icon, so the window asks Windows itself, through the shell's
  own call, the class of the window Qt keeps for its icon and the id Qt registers it by, which a later Qt may change:
  the window then cannot ask, logs so once, and trusts Qt.
- What Windows draws — the tray, the notifications, the title bar, the file dialogs — follows Windows, not the
  window's palette; the window's questions are its own and wear its palette.
- The suite covers the window's logic, the logo's and the tray icon's pictures drawn as pixels among it, and its
  windows on Qt's offscreen platform, with stand-ins for the tray icon and the account sync; the windows, the tray
  icon and its menu as Windows shows them, the notifications and the Start menu entry are checked by eye.
- A switch of the desktop app ends the Code sessions it hosts. The window asks first only where Claude Code's session
  registry says a turn is in progress, work the session delegated that still runs included, so an open session that
  is idle, or waiting on the person at a permission prompt or a question, ends without a question.
- Claude Code's session registry is an undocumented file of Claude Code's, read as measured (*Sources*): an update can
  change it. A file the reader does not recognise is named among the source problems and its session counts as not at
  work, so the keep-awake then holds nothing for it and the window's question before a switch leaves it out. A
  terminal session's file was not observed during a turn; that it reads `busy` then rests on the CLI's binary.
- The keep-awake is Windows only, and keeps the system awake, not the display. Whether its request keeps Claude Code
  running on a computer with modern standby once the screen turns off has not been measured, nor its holding on
  battery, which rests on its code consulting no power source, and on the tests.
- The sync's tests close a stand-in app (a copy of `powershell.exe` named `Claude.exe`, hosting a window that answers the
  end-of-session request), never the real one; how the real app answers the request is the app's own. The package's
  Windows service is stood in for by an entry added to the process list the script reads, since the suite registers
  nothing; the desktop tests need a user's session, because the script looks for the app's processes outside session 0.
  A switch in them reads the start-up lines a stand-in launcher writes to a log of the test's own, never the real app's.
- Whether the desktop app took the login a switch gave it is read from the app's own log, a text the app does not
  document (*Sources*). Should the start line's words change, every switch the app takes ends after a minute as done
  but unconfirmed, as does every add; should the signed-out lines' words change, a login the app refuses reads as a
  done switch again, and an add that reached the sign-in page as one whose app came up signed in. A
  good switch would be reported refused only were a start that stays signed in to write a signed-out line, which none
  did across the logs read, or were the user to sign out in the app within eight seconds of its start, which ends that
  login's web session in any case.
- The wait before a close rests on the app's own log and its cookie store, each measured on one version (*Sources*).
  Should the app stop writing its sign-in line, or word it otherwise, no wait happens, and a login stored within
  seconds of a sign-in may again lack its sign-in cookie: it is refused when put back, the note of exit 5 then naming
  that cause. Should the store come to write a change later than 35 seconds after it, a close after the wait and
  before that write stores the same.
- Whether a stored login's web session has ended is read from the app's own log, measured on one version (*Sources*).
  Should the app stop writing its line of a change of sign-in, or word it otherwise, the watcher sets nothing aside and
  a login a sign-out ended stays stored until a switch to it is refused, as before; should the app come to write the
  line of leaving a sign-in at a start or a close, a good login would be set aside and its account signed in to once
  more. A departure the watcher did not see — it was not running, and the app was on another account at its first
  look — is not judged, and is left to a refused switch.
- A refused switch is shown at once, a pass following it, but a sign-in in the app after it reaches the header only
  through the watcher's next look (15 seconds) and the service's next pass (60 seconds).
- The window runs the installed copy of the sync, `%USERPROFILE%\.claude\bin\WindowTallySync.ps1`: a copy installed
  before the switching modes, `AddDesktop` or `StartDesktop` were added refuses them, and `install.ps1 -Mode Install`
  updates it.
- Whether the desktop app runs reaches status.json through the watcher's next look (15 seconds) and the service's next
  pass (60 seconds), so an app closed or started by hand is said up to about 75 seconds late; a start the sync makes
  is said at once, by its event and the window's pass. Without a running watcher WindowTally says nothing of whether
  the app runs once the watcher's last view is two minutes old. The window shows its own start as starting for at most
  five minutes; a start that came to nothing is said by the first status written 20 seconds or more after it.
- Whether an add leaves the app at its sign-in page rests on the app deciding at its start from the sign-in cookie in
  its `Network\Cookies` file, measured on one version (*Sources*). Should a later one keep its sign-in elsewhere, the
  app comes up signed in after an add, the add ends 1 and says so, and an account is added through the app's own
  sign-out (*Rules*). The app so started still holds the account left's token cache in `config.json`; what it does with
  it is the app's own, and the switch back to that account shows whether its stored login stayed good.
- An add removes the app's whole `Network\Cookies` file, so a sign-in to any other site the app kept there goes with
  it; the login stored for the account left holds the whole file, and the switch back puts it back. Neither an add nor
  a switch touches the app's web storage (its IndexedDB and Local Storage) or the token caches beside the two login
  values.
- `SnapshotDesktop` reads a running app's mark before it closes the app, so that an app at its sign-in page is not
  closed for nothing: should the app write its mark only some time after a sign-in, a store asked for in that time is
  refused with nothing changed. An add reads the mark only once the app is closed.
- After an add or a refused switch records the app at its sign-in page, a sign-in there to the same account before the
  watcher's next look, within 15 seconds, is no change the watcher sees: WindowTally shows the app at its sign-in page
  until its next change, an app sample of that account or a switch. After an add, the app's switch on the card of the
  account left puts it right at once, a switch to the account the app is already on being recorded (*Rules*); after a
  refused switch that account's login is set aside, so its card explains how to add it instead.
- Without a running watcher (the `\WindowTally\Sync` logon task), a sign-in in the app after an add or a refused switch
  is not seen at all: WindowTally shows the app at its sign-in page until an app sample of an account it knows — the
  app samples about every 15 minutes while it runs, and an account just added is known only once the sync stores its
  profile — a switch, or the watcher's start.
- The CLI's sign-in file names no account, so the sync places it by the label and by when each was written (*Rules*,
  *The CLI's sign-in*). A refresh within the window of a label the app's Claude Code writes is taken for a sign-in to
  the label's account: the window spans the time between two looks, 15 seconds while the watcher runs and the time
  between launches without it, plus 30 seconds either side. A CLI that runs across a sign-in in the app and refreshes
  its token later leaves the sync unable to place the file, refusing until the label returns or a `claude auth login`
  through the launcher (`claude`, the account sync's `claude.cmd`) settles it; a `claude auth login` run by the CLI's
  own path is no witness, and is placed only where its two writes fall inside the window. A copy filed under another
  account before this rule stays as it is: nothing on the machine can tell whose session a stored copy holds, and a
  `claude auth login` to that account through the launcher replaces it.
- That a CLI has signed out rests on its sign-in file holding no pair of OAuth tokens, a shape inferred from the file's
  size, never seen. Should a CLI sign out leaving both tokens in place, the sync stores the file as a sign-in and says
  nothing. A signed-out CLI is said only while the CLI follows the app.
- The app's processes are listed through a CIM query of every process; where the query fails, each process's own path
  is read, which took many times as long on the development machine (2026-10-26), so that each listing in a close's
  wait is then slow.
