/**
 * Limit warnings: a toast the first time a window of the account this session uses reaches a threshold —
 * the 5-hour window at 80 % and 95 %, the weekly window at 70 % and 90 %, a per-model window (Fable's) at 80 % and
 * 95 % — judged on the exact readings the session receives, and for a per-model window, which no reading carries, on
 * the figure status.json gives it when a reading comes (`scopedWindows`). A reading carries only the windows the server
 * sent, so an account with no 5-hour limit is warned of its weekly window alone.
 *
 * "The first time" holds across sessions: the levels reached are kept in the plugin's store per account and
 * window, so a second session on the same account does not warn again. A window counts as a new one, and
 * warns afresh, when its reset time moved on by at least half the window's length, or when its percentage fell
 * by three points or more — a reset, by WindowTally's own rule for a fall; a per-model window's by twenty or more
 * (SCOPED_DROP_POINTS).
 *
 * A reading taken while status.json could not name the account is kept under `unattributed`; the first reading
 * that names the account takes that record over when it is the same window, so the warning is not repeated.
 * The store has no compare-and-set: two sessions crossing the same threshold in the same instant both warn.
 */

import type { ReadingWindow, StatusAccount } from '../types'

/** The kind of every per-model window; one model's is `weekly_scoped:<name>` (`scopedKind`). */
export const SCOPED = 'weekly_scoped'

/** Each kind's warning figures (windowtally/limits.py's WARNING_THRESHOLDS: the two change together). */
export const THRESHOLDS: Readonly<Record<string, readonly number[]>> = {
  five_hour: [80, 95],
  seven_day: [70, 90],
  [SCOPED]: [80, 95],
}

const WINDOW_MS: Readonly<Record<string, number>> = {
  five_hour: 5 * 3600_000,
  seven_day: 7 * 24 * 3600_000,
  [SCOPED]: 7 * 24 * 3600_000,
}

/** The kind one model's window is warned of and kept under: `weekly_scoped:Fable`. */
export const scopedKind = (name: string): string => `${SCOPED}:${name}`

/** The kind a window's figures and length are those of: a model's window's are every per-model window's. */
export const baseKind = (kind: string): string => (kind.startsWith(`${SCOPED}:`) ? SCOPED : kind)

/** A kind's warning figures; none for a kind WindowTally does not warn of. */
export const thresholdsOf = (kind: string): readonly number[] | undefined => THRESHOLDS[baseKind(kind)]

/**
 * An account's per-model windows as readings to warn on: each with a figure, as status.json gives it. Its figure may be
 * an estimate from the model's use since claude.ai was read; a fall of SCOPED_DROP_POINTS or more is the model's
 * allowance reset, and warns afresh.
 */
export function scopedWindows(account: StatusAccount | null): ReadingWindow[] {
  return (account?.weekly.scoped ?? []).flatMap(window => window.state === 'current' && window.percent !== null
    ? [window.resetsAt
      ? { kind: scopedKind(window.name), percentUsed: window.percent, resetsAt: window.resetsAt }
      : { kind: scopedKind(window.name), percentUsed: window.percent }]
    : [])
}

/** A fall of at least this many points is a reset, not rounding (windowtally/limits.py's DROP_POINTS). */
const DROP_POINTS = 3

/**
 * A per-model window's figure is the service's estimate between claude.ai readings, and a reading can set it a few
 * points lower; a reset of the model's allowance gives back all of it, so only a fall of this many points is a reset,
 * and a correction of the estimate does not warn again.
 */
const SCOPED_DROP_POINTS = 20

/** The store key the crossings are kept under. */
export const CROSSINGS_KEY = 'crossings'

/** The account scope of a reading taken while status.json could not name the account. */
export const UNATTRIBUTED = 'unattributed'

/** One window's state: when it resets, the highest threshold already warned of, the last percentage seen. */
export type Crossing = { resetsAt: number | null; level: number; percent: number }

/** Crossings by account (its UUID, or `unattributed`) and window kind. */
export type Crossings = Record<string, Record<string, Crossing>>

export type Warning = { kind: string; percent: number; threshold: number; resetsAt: number | null }

const isCrossing = (value: unknown): value is Crossing => {
  if (typeof value !== 'object' || value === null) return false
  const c = value as Record<string, unknown>
  return (c.resetsAt === null || typeof c.resetsAt === 'number') && typeof c.level === 'number'
    && typeof c.percent === 'number'
}

/** The stored crossings, keeping only well-formed entries: a store written by other code is not trusted whole. */
export function crossingsOf(stored: unknown): Crossings {
  const crossings: Crossings = {}
  if (typeof stored !== 'object' || stored === null) return crossings
  for (const [account, kinds] of Object.entries(stored as Record<string, unknown>)) {
    if (typeof kinds !== 'object' || kinds === null) continue
    for (const [kind, crossing] of Object.entries(kinds as Record<string, unknown>)) {
      if (isCrossing(crossing)) (crossings[account] ??= {})[kind] = crossing
    }
  }
  return crossings
}

/**
 * Lays the entries `after` changed relative to `before` onto `latest`, the store as it stands at write time, so
 * what another session wrote in between to other entries survives.
 */
export function mergeChanges(before: Crossings, after: Crossings, latest: Crossings): Crossings {
  for (const [account, kinds] of Object.entries(after)) {
    for (const [kind, crossing] of Object.entries(kinds)) {
      if (JSON.stringify(before[account]?.[kind]) !== JSON.stringify(crossing)) (latest[account] ??= {})[kind] = crossing
    }
  }
  for (const [account, kinds] of Object.entries(before)) {
    for (const kind of Object.keys(kinds)) {
      if (after[account]?.[kind] === undefined && latest[account]) delete latest[account][kind]
    }
  }
  return latest
}

/** Whether a reading of `percent`, resetting at `resetsAt`, belongs to the window `previous` describes. */
function isSameWindow(previous: Crossing, kind: string, percent: number, resetsAt: number | null): boolean {
  const span = WINDOW_MS[baseKind(kind)]
  const drop = baseKind(kind) === SCOPED ? SCOPED_DROP_POINTS : DROP_POINTS
  if (percent <= previous.percent - drop) return false
  return !(resetsAt !== null && previous.resetsAt !== null && span !== undefined
           && resetsAt - previous.resetsAt >= span / 2)
}

/** One window's next state after a reading, and the threshold to warn of, if one was newly reached. */
export function advance(previous: Crossing | undefined, kind: string, percent: number,
                        resetsAt: number | null): { crossing: Crossing; threshold: number | null } {
  const isNewWindow = previous === undefined || !isSameWindow(previous, kind, percent, resetsAt)
  const level = isNewWindow ? 0 : previous.level
  const reached = (thresholdsOf(kind) ?? []).filter(threshold => percent >= threshold && threshold > level)
  const threshold = reached.length ? Math.max(...reached) : null
  return {
    crossing: {
      resetsAt: resetsAt ?? (isNewWindow ? null : previous.resetsAt),
      level: threshold ?? level,
      percent,
    },
    threshold,
  }
}

/**
 * Applies a reading's windows to one account's crossings; returns the warnings it raises. An account's first
 * record of a window takes over the unattributed record of the same window.
 */
export function applyReading(crossings: Crossings, account: string, windows: readonly ReadingWindow[]): Warning[] {
  const warnings: Warning[] = []
  for (const window of windows) {
    if (thresholdsOf(window.kind) === undefined) continue
    const resetsAt = window.resetsAt ? Date.parse(window.resetsAt) : NaN
    const reset = Number.isFinite(resetsAt) ? resetsAt : null
    const kinds = (crossings[account] ??= {})
    let previous = kinds[window.kind]
    const orphan = account === UNATTRIBUTED ? undefined : crossings[UNATTRIBUTED]?.[window.kind]
    if (previous === undefined && orphan !== undefined
        && isSameWindow(orphan, window.kind, window.percentUsed, reset)) {
      previous = orphan
      delete crossings[UNATTRIBUTED]![window.kind]
    }
    const { crossing, threshold } = advance(previous, window.kind, window.percentUsed, reset)
    kinds[window.kind] = crossing
    if (threshold !== null) {
      warnings.push({ kind: window.kind, percent: window.percentUsed, threshold, resetsAt: reset })
    }
  }
  return warnings
}
