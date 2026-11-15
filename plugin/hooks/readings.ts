/**
 * The plan readings this plugin hands the ledger service: version 1 of the contract whose canonical statement
 * is windowtally/ingest_readings.py — one file per session, overwritten with the latest reading.
 *
 * A reading names no account; the service gives it the account the session's client was signed in to at the
 * reading's moment, checked against the reading's weekly reset (windowtally/attribution.py).
 */

import type { SessionRateLimit } from 'claude-code'
import type { Reading, ReadingWindow } from '../types'

export const READINGS_VERSION = 1

/** The reading for these windows at `t` (epoch ms), or null when none carries a figure. */
export function readingOf(t: number, sessionId: string, limits: readonly SessionRateLimit[]): Reading | null {
  const windows: ReadingWindow[] = []
  for (const limit of limits) {
    if (typeof limit.kind !== 'string' || !limit.kind || !Number.isFinite(limit.percentUsed)) continue
    windows.push(limit.resetsAt
      ? { kind: limit.kind, percentUsed: limit.percentUsed, resetsAt: limit.resetsAt }
      : { kind: limit.kind, percentUsed: limit.percentUsed })
  }
  return windows.length ? { v: READINGS_VERSION, t, sessionId, windows } : null
}

/** Whether two readings of one session carry the same figures, whatever their times. */
export function sameFigures(a: Reading | null, b: Reading): boolean {
  return a !== null && a.sessionId === b.sessionId && JSON.stringify(a.windows) === JSON.stringify(b.windows)
}
