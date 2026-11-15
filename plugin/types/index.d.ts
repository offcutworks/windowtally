/**
 * The plugin's state contract and the shapes it reads.
 *
 * StatusDocument mirrors version 3 of the ledger service's status.json, whose canonical statement is
 * windowtally/status_file.py; a change there is made on both sides together. The plugin reads what it shows: the
 * document's totals across the accounts, which only the window shows, are not read.
 */

/** One plan window of one account, as status.json states it. */
export type StatusWindow = {
  /**
   * five_hour: running | not_started | no_limit (the account has no 5-hour limit: no figure, no reset) | unknown;
   * weekly: current | unknown.
   */
  state: string
  percent: number | null
  resetsAt: string | null
  /** The observation the figures rest on. */
  asOf: string | null
  /** The percent or the reset time is inferred rather than read. */
  estimated: boolean
  exhaustsAt: string | null
  /**
   * The reset time came from a plugin reading (true), or was inferred or is absent (false); where the file does not
   * say, `estimated` stands for the reset time too.
   */
  anchorExact?: boolean
  /** The weekly window's use by product as claude.ai last reported it; absent where status.json gives none. */
  byProduct?: StatusByProduct
  /** The weekly window's per-model windows (Fable's); absent where the account has none to show. */
  scoped?: StatusScoped[]
}

/**
 * A model's own allowance inside the weekly window, as Fable's is, read from claude.ai through the browser extension
 * and carried forward by the service.
 */
export type StatusScoped = {
  /** The model's name as claude.ai shows it. */
  name: string
  /** current | unknown (a reset since its reading whose effect on it is not known). */
  state: string
  /** Of the model's own allowance; null while unknown. */
  percent: number | null
  resetsAt: string | null
  /** The claude.ai reading it rests on. */
  asOf: string | null
  /** A rise from the model's use since its reading, or a reset of its allowance, was inferred. */
  estimated: boolean
  /** The allowance as a percentage of the weekly window; null where claude.ai did not say. */
  allowanceOfWeekly: number | null
}

/** The week's use by product: when claude.ai computed it, and each product's whole-percent share, in its order. */
export type StatusByProduct = {
  asOf: string
  rows: { key: string; name: string; percent: number }[]
}

/** What the user's bills say about one account's subscription. */
export type StatusSubscription = {
  /**
   * active | ended | upcoming | none (no subscription bill) | unread (the account's bills could not all be read: its
   * plan, end and cost are null, and nothing is said of them but that).
   */
  state: string
  /** pro | max5x | ultra: the plan in effect today, null when no recorded period covers today. */
  plan: string | null
  planName: string | null
  /**
   * A UTC day, YYYY-MM-DD. While active, the end of the periods running on from today — the day the next would
   * start; once ended, the day the last one ended; before the first begins, the day it starts.
   */
  paidUntil: string | null
  /** While active: whole days from today to paidUntil. */
  daysLeft: number | null
  /** Within the renewal reminder's days of paidUntil; never set while the reminder is off. */
  renewSoon: boolean
  /**
   * The plans' cost at their US list price, in US dollars, on the days of today's UTC month: never what was paid. Null
   * only while unread.
   */
  thisMonthListPrice: number | null
  /** pro | max5x | ultra: the plan the account's profile names, null for any other. */
  profilePlan: string | null
  /** matches | differs | profile-older | no-bill-today | unknown-plan | no-profile | unread (not compared) */
  profileCheck: string
}

export type StatusAccount = {
  /** Names the account in every action. */
  uuid: string
  /** The account's e-mail, whatever its name. */
  email: string | null
  /** The name it is shown by: the user's own, at most 16 characters, else the e-mail's local part. */
  label: string
  isDesktop: boolean
  isCli: boolean
  lastActivity: string | null
  fiveHour: StatusWindow
  weekly: StatusWindow
  /** Null while no bill source exists. */
  subscription: StatusSubscription | null
  /** Whether a desktop-app login archive exists for this account; absent means false. */
  desktopArchived?: boolean
  /**
   * The user hid the account and neither the desktop app nor the CLI uses it, so no surface lists it; absent means it
   * is listed.
   */
  hidden?: true
}

export type StatusRecommendation = {
  account: string | null
  reason: string
  /**
   * With no account under the recommendation's ceilings: the first reset that frees one. With `account` null every
   * account is blocked and this is when the first opens; with one named it has the most left, and this is when room
   * returns.
   */
  reliefAt: string | null
  /** reliefAt came from a plugin reading; false where it was inferred, absent or the file does not say. */
  reliefExact: boolean
}

export type StatusDocument = {
  v: 3
  generatedAt: string | null
  desktopAccount: string | null
  cliAccount: string | null
  cliCondition: string | null
  sourceErrors: string[]
  recommended: StatusRecommendation
  /** The renewal reminder's days, which the user turns on; null while it is off. */
  renewalReminderDays: number | null
  /** The user's setting that silences WindowTally's notifications: while true, no limit toast is raised. */
  notificationsSilenced: boolean
  /** False while the desktop app is at its sign-in page, so no account's (desktopAccount null); absent means not. */
  desktopSignedIn?: false
  /**
   * False while the desktop app is not running, desktopAccount naming the account it starts on; absent means it runs
   * or whether it runs is not known. A session the app hosts never reads it false (status.ts, seenBySession).
   */
  desktopRunning?: false
  /** Whether the CLI follows the desktop app's account; absent means true. */
  syncFollows?: boolean
  /** Whether one-click desktop app switching is on; absent means unavailable. */
  oneClickDesktop?: boolean
  /** How many desktop-hosted Code sessions have a turn in progress; absent means 0. */
  workingSessions?: number
  /**
   * In the order every surface of WindowTally lists them, which a reader keeps: the desktop app's account, then the
   * CLI's where it is another, then the rest in the user's order, those whose subscription has ended after the others.
   */
  accounts: StatusAccount[]
}

/** One window of a plan reading, as Claude Code reported it with a response. */
export type ReadingWindow = { kind: string; percentUsed: number; resetsAt?: string }

/**
 * A plan reading as the plugin writes it: version 1 of the readings contract, whose canonical statement is the
 * windowtally/ingest_readings.py; `t` is epoch milliseconds.
 */
export type Reading = { v: 1; t: number; sessionId: string; windows: ReadingWindow[] }

/** What the plugin last made of status.json. */
export type StatusSnapshot =
  | { kind: 'ok'; path: string; mtimeMs: number; status: StatusDocument }
  | { kind: 'missing'; path: string }
  | { kind: 'unreadable'; path: string; problem: string }
  | { kind: 'unknown-version'; path: string; version: string }
  | { kind: 'no-home' }

declare module 'claude-code' {
  interface PluginState {
    'windowtally': {
      /** status.json as last read; null until the session's first read. */
      snapshot: StatusSnapshot | null
      /** The current minute (epoch minutes), so the countdowns redraw once a minute. */
      minute: number
      /** The reading this session last wrote, so the same figures are not rewritten at once. */
      lastReading: Reading | null
      /** Whether the band is folded to its tag on the desktop surface; kept in the plugin's store across sessions. */
      folded: boolean
      /** The panel's window button: whether a press is being carried out, and what the last one came to. */
      windowAsk: { isAsking: boolean; said: string | null }
      /** The user's silence of WindowTally's notifications, as the last status.json read whole gave it. */
      silenced: boolean
    }
  }
}
