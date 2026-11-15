/**
 * Reads the ledger service's status.json: version 3 of the contract whose canonical statement is
 * windowtally/status_file.py. The service replaces the file atomically, so a read never sees half a write.
 *
 * A version this plugin does not know — the version before included — is reported as such and never guessed at;
 * a file that is not the version-3 shape is reported with what is wrong, so a stale figure is never shown as a
 * fresh one. Every sum of money in it is in US dollars.
 */

import type {
  StatusAccount, StatusByProduct, StatusDocument, StatusScoped, StatusSubscription, StatusWindow, StatusSnapshot,
} from '../types'

export const STATUS_VERSION = 3

type Parsed = { status: StatusDocument } | { problem: string } | { version: string }

type Data = Record<string, unknown>

const isObject = (value: unknown): value is Data =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null)

const number = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

function windowOf(value: unknown): StatusWindow | null {
  if (!isObject(value) || typeof value.state !== 'string') return null
  const window: StatusWindow = {
    state: value.state,
    percent: number(value.percent),
    resetsAt: text(value.resetsAt),
    asOf: text(value.asOf),
    estimated: value.estimated === true,
    exhaustsAt: text(value.exhaustsAt),
  }
  if (typeof value.anchorExact === 'boolean') window.anchorExact = value.anchorExact
  const byProduct = byProductOf(value.byProduct)
  if (byProduct) window.byProduct = byProduct
  const scoped = scopedOf(value.scoped)
  if (scoped) window.scoped = scoped
  return window
}

/**
 * The weekly window's per-model windows, read as leniently as the use by product: a list not in its shape reads as
 * absent, the weekly window standing as it would without it (windowtally_gui/status_model.py reads it the same way).
 */
function scopedOf(value: unknown): StatusScoped[] | undefined {
  if (!Array.isArray(value) || !value.length) return undefined
  const rows: StatusScoped[] = []
  for (const row of value) {
    if (!isObject(row) || text(row.name) === null || text(row.state) === null) return undefined
    rows.push({
      name: text(row.name)!,
      state: text(row.state)!,
      percent: number(row.percent),
      resetsAt: text(row.resetsAt),
      asOf: text(row.asOf),
      estimated: row.estimated === true,
      allowanceOfWeekly: number(row.allowanceOfWeekly),
    })
  }
  return rows
}

/**
 * The weekly window's use by product, read more leniently than the rest: it is an addition no figure rests on, so one
 * that is not in its shape reads as absent, never as a fault of the file.
 */
function byProductOf(value: unknown): StatusByProduct | undefined {
  const asOf = isObject(value) ? text(value.asOf) : null
  if (!isObject(value) || asOf === null || !Array.isArray(value.rows)) return undefined
  const rows: StatusByProduct['rows'] = []
  for (const row of value.rows) {
    const key = isObject(row) ? text(row.key) : null
    const name = isObject(row) ? text(row.name) : null
    const percent = isObject(row) ? number(row.percent) : null
    if (key === null || name === null || percent === null) return undefined
    rows.push({ key, name, percent })
  }
  return { asOf, rows }
}

/**
 * An account's subscription: null where the contract says null, undefined where it is not the contract's shape. The
 * month's sum is null only on an account whose bills were not all read.
 */
function subscriptionOf(value: unknown): StatusSubscription | null | undefined {
  if (value === null) return null
  if (!isObject(value) || typeof value.state !== 'string') return undefined
  const thisMonthListPrice = number(value.thisMonthListPrice)
  if (thisMonthListPrice === null && !(value.state === 'unread' && value.thisMonthListPrice === null)) return undefined
  return {
    state: value.state,
    plan: text(value.plan),
    planName: text(value.planName),
    paidUntil: text(value.paidUntil),
    daysLeft: number(value.daysLeft),
    renewSoon: value.renewSoon === true,
    thisMonthListPrice,
    profilePlan: text(value.profilePlan),
    profileCheck: text(value.profileCheck) ?? '',
  }
}

function accountOf(value: unknown): StatusAccount | null {
  if (!isObject(value) || typeof value.uuid !== 'string' || !value.uuid) return null
  const fiveHour = windowOf(value.fiveHour)
  const weekly = windowOf(value.weekly)
  const subscription = subscriptionOf(value.subscription)
  if (!fiveHour || !weekly || subscription === undefined) return null
  const account: StatusAccount = {
    uuid: value.uuid,
    email: text(value.email),
    label: text(value.label) || text(value.email) || value.uuid.slice(0, 8),
    isDesktop: value.isDesktop === true,
    isCli: value.isCli === true,
    lastActivity: text(value.lastActivity),
    fiveHour,
    weekly,
    subscription,
  }
  if (value.desktopArchived === true) account.desktopArchived = true
  if (value.hidden === true) account.hidden = true
  return account
}

/** status.json's text as version 3, or what keeps it from being read as one. */
export function parseStatus(source: string): Parsed {
  let data: unknown
  try {
    data = JSON.parse(source)
  } catch (error) {
    return { problem: `it is not JSON (${error instanceof Error ? error.message : String(error)})` }
  }
  if (!isObject(data)) return { problem: 'it is not a JSON object' }
  if (data.v !== STATUS_VERSION) return { version: JSON.stringify(data.v ?? null) }
  if (!Array.isArray(data.accounts)) return { problem: 'it has no accounts list' }
  const accounts: StatusAccount[] = []
  for (const entry of data.accounts) {
    const account = accountOf(entry)
    if (!account) return { problem: 'one of its accounts is not in the version-3 shape' }
    accounts.push(account)
  }
  const recommended = isObject(data.recommended) ? data.recommended : {}
  const status: StatusDocument = {
    v: STATUS_VERSION,
    generatedAt: text(data.generatedAt),
    desktopAccount: text(data.desktopAccount),
    cliAccount: text(data.cliAccount),
    cliCondition: text(data.cliCondition),
    sourceErrors: Array.isArray(data.sourceErrors) ? data.sourceErrors.map(String) : [],
    recommended: {
      account: text(recommended.account),
      reason: text(recommended.reason) ?? '',
      reliefAt: text(recommended.reliefAt),
      reliefExact: recommended.reliefExact === true,
    },
    renewalReminderDays: number(data.renewalReminderDays),
    notificationsSilenced: data.notificationsSilenced === true,
    accounts,
  }
  if (data.desktopSignedIn === false) status.desktopSignedIn = false
  if (data.desktopRunning === false) status.desktopRunning = false
  if (data.syncFollows === false) status.syncFollows = false
  if (data.oneClickDesktop === true) status.oneClickDesktop = true
  const ws = number(data.workingSessions)
  if (ws !== null && ws > 0) status.workingSessions = ws
  return { status }
}

/** The snapshot for the file at `path` holding `source`, last changed at `mtimeMs`. */
export function snapshotOf(path: string, mtimeMs: number, source: string): StatusSnapshot {
  const parsed = parseStatus(source)
  if ('status' in parsed) return { kind: 'ok', path, mtimeMs, status: parsed.status }
  if ('version' in parsed) return { kind: 'unknown-version', path, version: parsed.version }
  return { kind: 'unreadable', path, problem: parsed.problem }
}

/**
 * The snapshot as a session reads it. A session the desktop app hosts runs inside the app, so the app runs whatever
 * the status last said: there `desktopRunning` is dropped, and only a status that outlived the app's last start says
 * otherwise. Elsewhere the snapshot stands as read.
 */
export function seenBySession(snapshot: StatusSnapshot, isDesktopSession: boolean): StatusSnapshot {
  if (!isDesktopSession || snapshot.kind !== 'ok' || snapshot.status.desktopRunning !== false) return snapshot
  const status = { ...snapshot.status }
  delete status.desktopRunning
  return { ...snapshot, status }
}

/** The account a session uses: the desktop app's in a session the app hosts, the CLI's otherwise. */
export function accountInUse(snapshot: StatusSnapshot | null, isDesktopSession: boolean): StatusAccount | null {
  if (snapshot?.kind !== 'ok') return null
  const uuid = isDesktopSession ? snapshot.status.desktopAccount : snapshot.status.cliAccount
  return snapshot.status.accounts.find(account => account.uuid === uuid) ?? null
}
