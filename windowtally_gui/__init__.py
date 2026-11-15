"""WindowTally's window — every account's standing, live, with its actions and the user's bills a click
away, in a window of its own and an icon in the tray.

Background
    The ledger service writes every account's standing to status.json each minute, and the desktop plugin draws it
    above the prompt of each Claude Code session. Outside a Code session nothing showed it; this window does, and it
    carries what the command line could do — read every source now, show the history and export it as HTML, open the
    data folder, record, change and remove bills, list bill files and set the renewal reminder — and it switches the
    desktop app and the CLI from one account to another with a click, on the account's card, in the Accounts menu and
    in the tray's. The desktop app lists a Code session only under the account it was filed under, so a switch of the
    app offers the sessions of the account it leaves, those a plan limit stopped first, then those at work and those
    whose background work is unfinished, and opens those chosen on the
    account switched to; and the Conversations window lists every account's Code sessions, from which one opens on the
    account in use, in the app or with a resume command for a terminal. It starts at logon into the tray (a logon task
    install.ps1 registers) and from the Start menu by hand.

Rules it keeps
    It sends no network request and reads no credential; it never switches an account itself and never touches the
    account sync's store. Switching an account, adding one at the app's own sign-in page, starting the desktop app the
    status reports not running and turning the sync's two switches are the sync script's work
    (``sync/WindowTallySync.ps1``), which the window starts as a process of its own and whose answer it reads
    (``sync_model``): the credentials code stays in one process and this window's code, which reads every response's
    transcript, in another. It asks before closing the desktop app where that would end
    Code sessions at work (Claude Code's session registry, ``windowtally.registry``). It shows what the service writes: the live
    figures are status.json's, version 3 of the contract the plugin reads (``windowtally.status_file``); account
    colours come from the ledger, opened read-only, and so does the History window's history, drawn from the figures
    layer the history page is written from (``windowtally.history``). Every figure, rule and write is WindowTally's own
    code — ``windowtally`` computes, validates and writes, this package only reads, asks and draws — so the window, the
    command line and the history page never disagree. A pass the window starts runs under the pass lock the service's
    own passes hold. It writes nothing of the desktop app's own: a session it carries to another account, or opens from
    the Conversations window, it hands to the app through the app's resume link, ``claude://resume?session=<id>``, and
    the app makes the session's card itself. Its notifications say only what the plugin never says, so none repeats a
    Code session's toast (``notices_model``). The user's setting that silences them is WindowTally's, kept in its
    settings, which a pass carries to the plugin in status.json, so one switch silences the window and every Code
    session together. The switch beside it, the keep-awake's, is kept in the same settings and read by the service,
    which holds the computer awake while a Code session works whether or not the window is open.

Structure
    __main__.py      pythonw -m windowtally_gui -> app_view.main
    app_view.py      The composition root: arguments, one window per user, the theme, the main window, the tray, the
                     clocks, the actions wired to WindowTally, the window's record, quitting.
    status_model.py  status.json read once after each change, as a typed snapshot; another version or shape refused.
    live_model.py    What the window, the tray's tooltip and its icon show, from one snapshot at one moment.
    notices_model.py The desktop notifications: a relief, a stopped service, a renewal, a new source problem.
    history_model.py The history over a span, computed off the window's thread; the span asked for and the one
                     shown; the History window's headings, summary tiles, notes, legends, charts, tables and switches.
    plot_model.py    The History window's line and column charts laid out as marks at a size in pixels and the
                     display's scale.
    table_model.py   A History window's table laid out as text at places in pixels, at the width it fills.
    tiles_model.py   The History window's summary tiles placed in columns of one width at a width in pixels.
    scroll_model.py  How far the wheel scrolls a view, which view a turn of it goes to, and when a chart's pointer
                     words may show.
    bills_model.py   The Bills and sources window's lists and its form, checked by WindowTally's own bill rules.
    actions_model.py What each button does, through WindowTally's code, answering in an Outcome.
    switch_model.py  What the cards and the menus offer for switching the desktop app or the CLI, from one status and
                     the sync's two switches as the window shows them; and what asking to switch leads to: the switch,
                     a question while Code sessions work, or an explanation where no login is stored.
    arrange_model.py The Arrange accounts window's logic: the accounts in the user's order, moved or put back in
                     order by name, the user's name for each, held to WindowTally's rules, and whether each is shown.
    sync_model.py    The sync script run as a process of its own: its command lines, its notes and exit code, whether
                     a run can still be called off, and the terminal that signs the CLI in.
    flow_model.py    A switch, or a start of the desktop app, from the window's side: the wait for the sessions or for
                     a running CLI, the run, the header's progress, calling it off, and what the window must answer.
    carry_model.py   The sessions a switch of the desktop app offers to carry to the account switched to, in the order
                     they stand and as the list words them, and the queue that opens those chosen through the app's
                     resume link once the switch is done.
    conversations_model.py Every account's Code sessions as the Conversations window lists them, read off the window's
                     thread; the search and the two filters; the line naming the account a session opens on; the
                     resume command.
    background.py    Work run off the window's thread — a pass — and its result handed back.
    instance_model.py One window per user: the window lock and a second start's request to show it.
    state_model.py   window.json: the window's place, keep-on-top, the theme chosen, the notices already given;
                     fitting a place to the monitors attached now.
    theme_model.py   The colours by role in both modes, from WindowTally's palette; the theme the user chooses: follow
                     Windows' light or dark mode, or keep to light or to dark whatever Windows asks.
    motion_model.py  Whether anything moves, and how: a ring's sweep to a changed figure, the slow pulse at a warning,
                     nothing at rest and nothing while Windows' animation effects are off.
    logo_model.py    The logo, two rings on a dark tile, drawn as pixels from its geometry at any size; PNG and icon
                     file encoding.
    tray_model.py    The tray icon's picture: the logo's rings showing the account in use's windows live.
    tray_check_model.py Whether Windows holds the tray icon, and what the window does while it does not.
    card_model.py    An account card's layout with no toolkit: the hollow of its colour's ring for an account whose plan
                     has ended, where a line's pieces of text go at a width, and a per-model window's bar.
    about_model.py   The About window's words: its release named from the build record the copy ships, its copyright
                     line read from the licence it ships.
    shortcut.py      The Start menu entry and its icon file, written and removed for install.ps1 from a task outside
                     the desktop app.
    formatting.py    Times, spans, days and percentages as the plugin writes them.
    common_view.py   The window's idioms: the application identity, sizes from the font, a place in the display's
                     pixels, the monitors' working areas, the wheel's one router, the scrolling frame, the words
                     window, hints, the list of records with its tick boxes and its current row's mark, and the holder
                     that ends a list on a whole row.
    theme_view.py    The one presentation mechanism: the colour scheme, the palette and one style sheet, from roles, the
                     fonts, the page ground, the title bars' tint and the one clock what moves draws from; the one door
                     from a role to a text colour.
    main_view.py     The main window.
    cards_view.py    An account's card and the line of an account whose plan has ended: rings, a per-model window's
                     bar, swatch, chips, the pieces of a line, the switch buttons; the meter a share's bar takes.
    switch_view.py   The switch menus, written afresh each time one is posted, and the dialogs: the sessions to carry
                     to the account switched to, Code sessions at work, a CLI that is running, Add an account.
    arrange_view.py  The Arrange accounts window.
    conversations_view.py The Conversations window.
    bills_view.py    The Bills and sources window.
    history_view.py  The History window: the spans, Recompute, Export HTML…, the summary's tiles and the history page's
                     sections in one column.
    plot_view.py     A chart painted from ``plot_model``'s marks, with what each mark is on pointing, and its legend.
    table_view.py    A History window's table painted from ``table_model``, a long one scrolling within itself under its
                     headings.
    about_view.py    The About window (Help menu) and the window of text it opens for the licence and the notices.
    tray_view.py     The tray icon and its notifications through ``QSystemTrayIcon``; whether Windows holds the icon,
                     asked of the shell directly.

Architecture
    One dependency direction: this package -> ``windowtally``; the service never imports it, so the service stays free
    of any toolkit and needs Python's standard library alone. Inside, a ``*_model.py`` file holds a sub-feature's logic
    and imports no toolkit, and its ``*_view.py`` file builds the widgets with Qt Widgets, through PySide6; only
    ``*_view.py`` files import PySide6 (``shortcut.py``, ``formatting.py`` and ``background.py`` are logic too), so the
    models are tested without a display.

    The package stays one flat folder because ``install.ps1`` copies its top-level ``*.py`` alone and compares the whole
    tree: a module in a folder of its own would not be installed, and would read as a difference.

Design patterns
    - Snapshot in, words out: every surface is a function of one snapshot of status.json at one moment, so the window,
      the tooltip and the icon agree; the window's widgets are made once and updated in place each second.
    - Background work, foreground widgets: a pass, and apart from it the History window's computation and the
      Conversations window's read of the sessions, each runs on a thread of its own; only the window's thread touches a
      widget, and it polls for their results.
    - Requests, not commands, between processes: a second start asks the running window to show itself through a
      file; a pass waits on the data folder's pass lock rather than on another process; a switch is asked of the sync
      script, which decides and does it, and the window shows the notes and the exit code it answers with.
    - One offer, every surface: the cards, the Accounts menu and the tray's menu take what they offer from
      ``switch_model``, and the two switches from one reading, so they cannot disagree; the user's change of a switch
      stands in the window until a status written after it confirms it.
    - One order, kept rather than made: the cards, the menus and the tooltip list the accounts in status.json's order,
      which the service writes from the user's settings, and leave out those it marks hidden; the Arrange accounts
      window writes those settings through ``windowtally.settings`` and runs a pass, and is the one place that shows
      the user's order itself, without the accounts in use pulled first, and every account, a hidden one included. It
      lays what it changed onto the settings as they stand when it writes, under the file's edit lock, so a change made
      to them by hand while it is open is undone only after the window has said so.
    - Explanation behind a hint: a window shows at rest names, values, state and refusals; what a figure, a field or
      a control means is a hint (``common_view.Hint``) — a History section's behind a ? beside its heading, as the
      history page and the export give it in the heading's tooltip — so no sentence stands on a surface twice.
    - One presentation entry point (``theme_view.Theme.apply``), at first paint and at every change of mode: the
      palette, the style sheet, and what follows the mode beside them — the page ground's colours, read while it
      paints, and the title bars' tint.
    - One look, restrained and tight (a design language in a dark mode, its showcase, and a light one): a page ground,
      under a fine grid in the dark mode alone, raised cards with hairline edges that nothing changes under the pointer,
      chips of one neutral tint, one quiet button form and the filled one for the recommended switch alone, figures in
      the words' family with tabular digits, glow only on data and in the dark mode alone, and motion only on a change
      of value and as a slow pulse at a warning (``motion_model``), drawn from one clock that runs only while something
      moves; with Windows' animation effects off nothing moves. A card shows its two windows as concentric rings that
      echo the logo and the tray icon (``windowtally.rings``, the history page's rings too), beside their figures, a
      per-model window as a thin bar under them, and the account in use by a strip of its colour. The History,
      Bills and sources
      and Conversations windows stand on the page ground too, the dialogs on the plain page; the History window draws
      each account's share as a bar in its colour, a shade under each chart line and, in the dark mode, a glow along
      it, and its tables as panels on the cards' surface. Glow is painted as strokes and fills, never a graphics
      effect, so a repaint costs no offscreen render.
    - Said when it matters: a card says a reading's age only once the reading may be out of date, a plan's days left
      only while its renewal is near, and the main window its source problems only while there are any; the header
      names which account each client uses only where the cards' chips cannot. Each bound is derived from what
      status.json carries, never a setting.
    - One drawing of the logo: the window's icon, the tray's rings, the About window and the Start menu entry's icon
      file are all drawn by ``logo_model`` from its geometry, each at its own size; the program keeps no image, and the
      README's picture is a copy of the drawing that a test holds to it.

Caveats
    - On Windows a notification goes through the tray icon, so a window whose icon could not be made raises none.
      Qt's tray icon says nothing of whether Windows holds it, so the window asks Windows itself, through the window
      class Qt names for its icon and the id it gives it; a Qt that changes either leaves the question unasked, logged
      once, and the window trusting Qt.
    - The window reads status.json only after its modification time changes: on Windows the service's replace of the
      file waits while a reader holds it (WindowTally's writers retry a refused replace), so the window holds it as
      rarely as it can.
    - What the desktop app and Windows draw — the tray, the notifications, the file dialogs — follows Windows, not the
      window's palette; the title bar is Windows' own too, in the light or dark mode the window wears, tinted to the
      page colour on Windows 11 and left as Windows draws it elsewhere. The window's questions are its own and wear its
      palette.
    - A widget the style sheet styles is drawn by Qt's style-sheet style rather than Windows 11's, so a control the
      language restyles carries a rule for every state the window puts it in (hover, pressed, focus, disabled); a
      control it leaves to the style — the check boxes, the combo box itself — is drawn from the palette's roles. A
      list's tick boxes are not left to it: inside a list the sheet gives a frame, Windows 11's style draws a ticked box
      blank, so a list draws its own (``common_view.TickDelegate``). Nor is the mark of the row the keyboard is on:
      Windows 11's style frames it in the text colour, a harsh white box in the dark mode, so a list draws a strip of
      the focus colour in its place (``common_view.RowDelegate``).
    - A switch of the desktop app closes it, and with it the Code sessions it hosts, the one the user may be typing in
      included. The window asks first only where Claude Code's session registry says a turn is in progress, work the
      session delegated that still runs included; a session that is idle but open, or waiting on the person at a
      permission prompt or a question, ends without a question.
    - The window runs the installed copy of the sync script (``~/.claude/bin``): a window installed without the sync
      that holds the switching modes gets the script's refusal to read the mode, which it says as it is.
    - The app's resume link is no interface the app documents: an update can change it, and a session opened through
      it loses its effort and may fall back to the default permission mode, so the switch's dialog and the
      Conversations window say what each session last ran with, the window says at every switch that carries one
      that both are set again and, of every session it hands over whose effort or mode it knows, what it ran with;
      the resume command passes both to the CLI. Whether the app took a link is not known to the window, only whether
      the shell could hand it on. It was measured adopting sessions the app's Code tab ran, so the Conversations
      window hands it no session the CLI alone ran, which has no card in the app.

Design direction
    The window draws and asks; it never computes a figure of its own. A further view takes its figures from WindowTally's
    package, as the History window takes the history page's, so every surface of WindowTally says one thing the same way.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
