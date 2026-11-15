"""WindowTally — the permanent ledger and live standing of several Claude subscription accounts.

Background
    WindowTally serves one person with several Claude subscription accounts on one Windows machine, who works in
    the Claude desktop app's Code tab and the Claude Code CLI and moves between the accounts as their limits
    fill; the account sync (``sync/`` beside this package) keeps the CLI on the desktop app's account. Each
    account has a weekly window with a fixed reset time, and, where its plan has one, a 5-hour window, which
    starts with the first message after the previous one ended; Anthropic now and then hands out a reset outside the
    weekly schedule — of the week, or of a model's own allowance — free and not for sale, which the user takes when
    they choose, and removes the 5-hour limit from some accounts. WindowTally reads an account as
    having no 5-hour limit when its readings stop carrying that window, and judges it by its week alone
    (``limits``). This package keeps a per-account record of what was used and computes every account's
    current standing from it.

Sources — all local and read-only; WindowTally sends no network request and reads no credential
    - Claude Code transcripts under ``~/.claude/projects``: one record per model response with its model,
      requested model, effort, speed, token counts and session; a desktop session names its owning account; each
      session's title and the permission mode its main transcript last named, each turn of a main session a plan limit
      refused, and each background task a main session started, with its end where a transcript says it ended.
    - The desktop app's plan-usage history (``%APPDATA%/Claude/plan-usage-history.json``): the signed-in
      account's 5-hour and weekly percentages, sampled while the app runs and kept about 30 days by the app.
      Its sampling is not continuous, so it is history, never the live source.
    - Plan readings the desktop plugin writes into WindowTally's data folder: the percentages and exact reset times
      Claude Code receives with each response. These are the live source.
    - Claude Code's own session registry, ``~/.claude/sessions``: one file per running Claude Code process, naming
      its session and whether a turn is in progress (``registry``), for the desktop app's sessions, a terminal's and
      a scripted run's alike. The service keeps the computer awake while it names a session at work, and the window
      asks before it closes the client while it names one of the desktop app's. The ``.key`` files Claude Code keeps
      beside them are never opened.
    - Browser readings, where the optional Chrome extension (``extension/`` beside this package) is loaded: the
      5-hour and weekly percentages and exact reset times claude.ai's own page receives, per organization, and the
      week's use split by product (Claude Code, Chats, Cowork, Other) where the page receives it, which the
      extension hands to the native-messaging host (``browser_host``) and the host writes into the data folder.
      The extension sends no request and reads no credential; without it WindowTally stands whole, and chat on
      claude.ai in a browser shows only once the desktop app or Claude Code next reads the account.
    - The account sync's records in ``~/.claude/accounts``: one non-secret profile per stored account, its
      change events, its watcher view, its two switches (``sync-settings.json``) and the older ``sync.log``. A
      profile names the plan the account is on now, and nothing else about what it costs. Whether an account's
      desktop login is stored is read off the archive's presence; the archive is never opened.
    - What no file on the machine says, the user writes: the subscription bills — WindowTally's own bills file in
      its data folder, and any further bill file WindowTally's settings name, such as a bill archive's manifest —
      and those settings themselves.

Structure
    paths           every location, from three roots; overridable for tests
    accounts        the account registry; the user's names for the accounts, and the user's order, applied to it
    pricing         list prices: the API's, for an API-equivalent cost of each response, and the plans'
    ledger          the SQLite store and its schema — the permanent record
    timeutil        timestamp parsing shared by the ingesters
    files           whole-file writes that wait out a reader; the edit locks and WindowTally's one lock primitive
    ingest_*        one module per source; each is incremental and idempotent
    browser_host    the browser extension's native-messaging host, which writes its readings, and its registration
                    with Chrome — the one part of the package Chrome starts
    attribution     which account each response, limit stop and reading belongs to
    sessions        the Code sessions the ledger holds, for the window: every account's, each one's title, folder, last
                    activity, account and use, and the desktop sessions of an account that a switch of the app can
                    carry to another, with the limit stop that stands and the background tasks left unfinished
    limits          window standings, extra resets, projections, the recommendation, blocked time
    settings        ``settings.json``: further bill sources, the band's renewal reminder, the notifications' silence,
                    the keep-awake's switch, the accounts' order, the user's names for them and the accounts the user hid
    bills           the bill model, WindowTally's own bills file, and every bill source read into one list
    bills_manifest  a bill archive's manifest read as bills; imported only when a source names it
    billing         what the bills say: plan periods and changes, gaps, the plans' cost per month at list price,
                    days with a plan, how far each account is paid up, the profile check, each period's
                    API-equivalent use
    plan_use        what the plans covered of the API-equivalent use — less the use at extra usage, while a window stood
                    exhausted or past a model's own allowance, and, without resets, less the use beyond one window a
                    week — and the weekly window's resets outside its schedule, by kind: extra, a model's allowance's,
                    or not known
    capacity        what a plan's windows hold: the API-equivalent dollars a full 5-hour and weekly window held, from
                    the readings of the accounts the bills put on the plan, the plans' dollars alone
    products        the weekly window's use by product as claude.ai reports it: each account's current report and
                    each window's last, an addition no other figure rests on
    registry        Claude Code's session registry: the live sessions, which of them have a turn in progress, and
                    which the desktop app hosts
    keep_awake      the Windows power request the service holds while a session works, and the thread that looks at
                    the registry and the switch every two seconds to hold or release it
    status_file     ``status.json``, the contract the desktop plugin and the window read
    sync_store      the sync store's two switches and desktop archives, as the service reads them for ``status.json``
    palette         WindowTally's colours, light and dark, for the history page and the window
    rings           an account's two windows as concentric rings — their geometry and each arc's colour — which the
                    window's cards paint and the history page's write as SVG
    history         the history's figures and words over a range — the summary, weekly use, cost per day or week,
                    tokens per day, week and month, subscriptions, what a full window holds, exhausted time, sessions,
                    models, effort, context, coverage — which the page and the window both draw
    charts          the history page's inline SVG charts
    dashboard       the self-contained HTML history page: the figures layer's content in markup, with the account
                    cards; and the same markup over one span without them, the file the window's History view exports
    service         one pass over every source, and the background loop
    release         a release's build record, which names the release a copy is; the release build writes it
    __main__        the command line

Design
    Facts are stored as read; interpretation is computed when asked. A response row keeps its raw usage and
    session, and its account — the one its client was signed in to at that moment — is re-derived whenever better
    evidence arrives — a sync event, an app sample, an owner line written later — or the rule deriving it changes,
    so an early guess never becomes permanent. Whether an account has a 5-hour limit is likewise read off its
    readings, never set: the readings that stop carrying the window remove it, and the next that carries one
    restores it.
    An idle account needs no polling. Its weekly percentage only falls at a reset, and a 5-hour window past
    its end stays not-started until the next message, so its standing is its last observation rolled forward
    through the reset times, shown with that observation's age.
    A figure is computed once, wherever it is shown: the history page and the window's History view draw the same
    figures layer (``history``), each adding only its own markup or widgets, so the two cannot disagree.
    An account has one name and one place across WindowTally's live surfaces. The user's names and order are settings;
    a pass gives the accounts their names where it reads them, so every word that names one names it so, and writes
    status.json's accounts in the order every surface lists them — the accounts in use first, then the user's order,
    those whose plan has ended after the others (``status_file``) — so the window, the tray, the band and the panel
    keep an order rather than make one. The history keeps the order the accounts were first seen in, which its colours
    follow; a rename moves no colour.
    A name is for showing only: every action names an account by its UUID.
    An account the user hid stays in status.json, marked, while neither client uses it, so every live surface leaves
    it out by one mark and the window can still show it again; the history keeps every account. The recommendation
    weighs no account the user hid, nor one whose bills record a plan that has ended: such an account takes no
    readings, so its standing, rolled forward through its resets, would read as room left.
    Bills are the user's own files, which do not expire, so the ledger keeps no copy of them: every pass reads
    them whole, and every figure they give is computed afresh. Every bill source reaches one bill model, which
    is all ``billing`` reads, so a further source format is one more reader beside ``bills_manifest``. A source
    gives what it can: a bill it cannot read is left out alone and named, and the accounts it may concern are
    marked as not wholly read, so that no surface states an absence — no bills, no plan today, an end, a gap, a sum
    of nothing — whose cause may be a bill not read; writing a bills file stays strict. Every
    subscription cost WindowTally shows is the plans' US list price in US dollars (``pricing``), so it stands beside
    the API-equivalent figures in one currency: nothing is converted, and a bill's own amount and currency are
    shown only where bills are recorded or listed, written alike for every currency.

Caveats
    - The sources expire (the app keeps about 30 days of samples; Claude Code prunes old transcripts), so the
      ledger is the only lasting copy: a schema change migrates it and never rebuilds it.
    - Chat-tab conversations leave no local token record; they show only in the percentages.
    - A session's title has no time in its transcript, so the ledger keeps the one read last; the title the desktop
      app shows stands before the one Claude Code makes up itself.
    - An account used on another device changes without a local trace until it is next used here.
    - Claude Code's session registry is an undocumented file of Claude Code's, read as measured: an update of Claude
      Code can change it. A file the reader does not recognise is named among the source problems and its session
      counts as not at work, so the keep-awake then holds nothing for it, and the window's question before a switch
      leaves it out.
    - The keep-awake is Windows only, and keeps the system awake, not the display; whether it keeps Claude Code
      running on a computer with modern standby once the screen turns off was not measured.
    - A weekly reset time inferred from the app's samples is approximate (the samples are sparse); the first
      plugin or browser reading for that account replaces it with the exact time.
    - What a plan's full window holds is counted as though all of an account's use were Claude Code here: the
      readings also rise with the account's Chat-tab, browser and other-device use, which costs nothing here, so the
      figure is a lower bound wherever an account is used otherwise. It knows an account's plan only from the bills.
    - What the plans covered is read off the readings alone (``plan_use``): use at extra usage is found where a window
      stood exhausted or a model's allowance full by its readings or its carried estimate, and a reset outside the
      schedule only where readings bracket its fall, so a reset while no reading was taken, or one of under
      ``limits.DROP_POINTS``, leaves no trace.

Design direction
    WindowTally stays passive: an idle account's standing comes from what official clients already wrote on this
    machine, never from a request made with stored credentials.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
