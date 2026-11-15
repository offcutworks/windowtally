/**
 * WindowTally's desktop plugin: loaded at user scope in every Claude Code session, the desktop app's Code
 * tab and the CLI alike.
 *
 * What it does
 *   readings   after each turn that made model requests, and whenever a plan window moves a whole point, the
 *              session's latest plan-limit reading goes to WindowTally's data folder (readings.ts), where the ledger
 *              service ingests it; nothing is written while that folder does not exist.
 *   band       above the prompt, from the service's status.json (status.ts, band.tsx), the session's own account
 *              set apart: one line on the terminal; on the desktop two columns, the fold button over Details beside
 *              the account in use on a line of its own over the others, the fold's state kept in the plugin's
 *              store. Its Details button opens and closes the panel (panel.tsx).
 *   window     the panel's head carries a button that brings up the WindowTally window (window.ts).
 *   warnings   a toast when the session's account first reaches a limit threshold (alerts.ts), none while
 *              status.json says the user silenced WindowTally's notifications.
 *
 * What it never does: register a command or a tool, or touch a prompt, a tool list or the model's context. It
 * observes `session.start`, `turn.complete` and `session.measure`, draws two render sites, reads and
 * writes only WindowTally's data folder and its own store, and sends no request. It runs one program, Windows'
 * schtasks.exe, and only when the panel's window button is pressed with no WindowTally window running: to run the window's
 * logon task, and to ask whether that task is registered when it did not run.
 *
 * Caveats
 *   - The function-hook API is early access, and the desktop app runs a Claude Code build of its own beside the
 *     CLI's: a change here is validated and tested under both builds.
 *   - The engine follows `$` only into functions declared at this file's top level or imported from the
 *     plugin's own files, so the helpers below are top-level functions. What they remember lives in `$.state`
 *     (the session's, kept across reloads) and `$.store` (across sessions), not in module variables.
 *   - status.json is polled by its modification time (STATUS_POLL_MS); the service rewrites it every minute.
 */

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionRateLimit } from 'claude-code'
import type { StatusAccount, Reading, StatusSnapshot } from '../types'
import {
  applyReading, baseKind, CROSSINGS_KEY, crossingsOf, mergeChanges, SCOPED, scopedWindows, UNATTRIBUTED,
  type Crossings, type Warning,
} from './alerts'
import { bandTree, desktopBandTree } from './band'
import { panelTree } from './panel'
import { dataPaths, readingPath } from './paths'
import { isHostedByDesktop } from './hosting'
import { readingOf, sameFigures } from './readings'
import { accountInUse, seenBySession, snapshotOf } from './status'
import { span, when } from './text'
import { bringUpWindowSafely } from './window'

export const PANE = 'windowtally'
const STATUS_POLL_MS = 15_000
const TOAST_MS = 10_000
/** A reading with the figures of the last one written is written again only after this long, to renew its time. */
const REWRITE_AFTER_MS = 60_000
/** The store key the desktop band's fold is kept under, so a session starts as the last fold left the band. */
const FOLDED_KEY = 'bandFolded'

const snapshot = atom({ plugin: 'windowtally', key: 'snapshot' } as const, null)
const minute = atom({ plugin: 'windowtally', key: 'minute' } as const, 0)
const lastReading = atom({ plugin: 'windowtally', key: 'lastReading' } as const, null)
const folded = atom({ plugin: 'windowtally', key: 'folded' } as const, false)
const windowAsk = atom({ plugin: 'windowtally', key: 'windowAsk' } as const, { isAsking: false, said: null })
const silenced = atom({ plugin: 'windowtally', key: 'silenced' } as const, false)

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error))

function warningText(label: string | null, warning: Warning, now: number): string {
  const scoped = baseKind(warning.kind) === SCOPED
  const window = warning.kind === 'five_hour' ? '5-hour window'
    : scoped ? `${warning.kind.slice(SCOPED.length + 1)} allowance` : 'weekly window'
  const reset = warning.resetsAt === null ? ''
    : warning.kind === 'five_hour' ? `; it resets in ${span(warning.resetsAt - now)}`
    : `; it resets ${when(warning.resetsAt)}`
  // Past a model's allowance the model goes on at usage credits, outside the plan.
  const after = scoped ? '; past it, the model uses usage credits' : ''
  const who = label ? `${label}: ` : ''
  return `${who}${window} at ${Math.round(warning.percent)}%, past ${warning.threshold}%${reset}${after}.`
}

/**
 * Keeps the snapshot, and the user's silence as the last status.json read whole gave it: a read that failed, or a
 * file gone, leaves the silence as it stood.
 */
async function show($: EngineInterface, next: StatusSnapshot): Promise<void> {
  if (JSON.stringify(await read($, snapshot)) !== JSON.stringify(next)) await update($, snapshot, () => next)
  if (next.kind === 'ok' && (await read($, silenced)) !== next.status.notificationsSilenced) {
    await update($, silenced, () => next.status.notificationsSilenced)
  }
}

/** Moves the minute on, and reads status.json again unless the snapshot already holds this version of it. */
async function refresh($: EngineInterface): Promise<void> {
  const thisMinute = Math.floor((await $.clock.now()) / 60_000)
  if ((await read($, minute)) !== thisMinute) await update($, minute, () => thisMinute)
  const where = await dataPaths($)
  if (where === null) return show($, { kind: 'no-home' })
  let mtimeMs: number
  try {
    mtimeMs = (await $.fs.stat(where.status)).mtimeMs
  } catch {
    return show($, { kind: 'missing', path: where.status })
  }
  const current = await read($, snapshot)
  if (current?.kind === 'ok' && current.path === where.status && current.mtimeMs === mtimeMs) return
  let source: unknown
  try {
    source = await $.fs.read(where.status)
  } catch (error) {
    return show($, { kind: 'unreadable', path: where.status, problem: message(error) })
  }
  return show($, typeof source === 'string'
    ? snapshotOf(where.status, mtimeMs, source)
    : { kind: 'unreadable', path: where.status, problem: 'it was not read as text' })
}

/**
 * Toasts each threshold this reading's windows reached first, for the account the session uses, and each its
 * per-model windows reached as status.json last gave them (alerts.ts, scopedWindows). A session that
 * draws nowhere (a `-p` run, an SDK host) neither warns nor records the crossing: nobody would see the toast, so
 * the warning is left for a session that draws. While the user has silenced WindowTally's notifications the crossing is
 * recorded as warned of and no toast is raised, so letting them be raised again brings no stale warning.
 */
async function warn($: EngineInterface, reading: Reading): Promise<void> {
  const surfaces = await $.session.surfaces()
  if (!surfaces.length) return
  const isSilenced = await read($, silenced)
  let isDesktopSession = surfaces.includes('desktop')
  try {
    isDesktopSession = await isHostedByDesktop($, surfaces)
  } catch (error) {
    $.ui.log(`windowtally: desktop hosting not read for the limit warnings: ${message(error)}`, { to: 'debug' })
  }
  const account = accountInUse(await read($, snapshot), isDesktopSession)
  const before = crossingsOf(await $.store.get(CROSSINGS_KEY))
  const after: Crossings = JSON.parse(JSON.stringify(before))
  const warnings = applyReading(after, account?.uuid ?? UNATTRIBUTED, [...reading.windows, ...scopedWindows(account)])
  if (JSON.stringify(after) !== JSON.stringify(before)) {
    await $.store.set(CROSSINGS_KEY, mergeChanges(before, after, crossingsOf(await $.store.get(CROSSINGS_KEY))))
  }
  for (const warning of warnings) {
    const text = warningText(account?.label ?? null, warning, reading.t)
    if (isSilenced) $.ui.log(`windowtally: silenced: ${text}`, { to: 'debug' })
    else $.ui.toast(text, { timeoutMs: TOAST_MS })
  }
}

/** Writes the session's reading for these windows, then raises the warnings it calls for. */
async function record($: EngineInterface, limits: readonly SessionRateLimit[]): Promise<void> {
  const where = await dataPaths($)
  if (where === null || !(await $.fs.exists(where.folder))) return
  const reading = readingOf(await $.clock.now(), await $.session.id(), limits)
  if (reading === null) return
  const last = await read($, lastReading)
  if (!(sameFigures(last, reading) && reading.t - (last?.t ?? 0) < REWRITE_AFTER_MS)) {
    const path = readingPath(where, reading.sessionId)
    try {
      await $.fs.write(path, JSON.stringify(reading))
      await update($, lastReading, () => reading)
    } catch (error) {
      $.ui.log(`windowtally: cannot write ${path}: ${message(error)}`, { to: 'debug' })
    }
  }
  await warn($, reading)
}

async function recordSafely($: EngineInterface, limits: readonly SessionRateLimit[]): Promise<void> {
  try {
    await record($, limits)
  } catch (error) {
    $.ui.log(`windowtally: reading not recorded: ${message(error)}`, { to: 'debug' })
  }
}

async function toggleDetails($: EngineInterface): Promise<void> {
  if ((await $.ui.panes()).some(pane => pane.id === PANE)) await $.ui.close({ id: PANE })
  else await $.ui.open({ id: PANE, title: 'WindowTally', closeOnEscape: true })
}

/**
 * Brings up the WindowTally window, saying under the panel's button what came of it. A press while one is being carried
 * out is ignored: the first is still waiting on the window.
 */
async function askWindow($: EngineInterface): Promise<void> {
  let isFree = false
  await update($, windowAsk, ask => {
    isFree = !ask.isAsking
    return isFree ? { isAsking: true, said: null } : ask
  })
  if (!isFree) return
  const said = await bringUpWindowSafely($)
  await update($, windowAsk, () => ({ isAsking: false, said }))
}

/**
 * Takes the fold the store keeps; anything there but `true` leaves the band unfolded. A store that cannot be read
 * costs the fold, never the band: the failure is logged and the session goes on.
 */
async function restoreFold($: EngineInterface): Promise<void> {
  try {
    const stored = (await $.store.get(FOLDED_KEY)) === true
    if ((await read($, folded)) !== stored) await update($, folded, () => stored)
  } catch (error) {
    $.ui.log(`windowtally: band fold not restored: ${message(error)}`, { to: 'debug' })
  }
}

/**
 * Folds or unfolds the desktop band, and keeps the fold for the sessions that start after. The flip is applied to
 * the value as it stands when written, so two quick presses fold and unfold rather than both folding.
 */
async function toggleFold($: EngineInterface): Promise<void> {
  let next = false
  await update($, folded, value => (next = !value))
  try {
    await $.store.set(FOLDED_KEY, next)
  } catch (error) {
    $.ui.log(`windowtally: band fold not kept: ${message(error)}`, { to: 'debug' })
  }
}

/**
 * The snapshot as the session reads it (status.ts, seenBySession), and the account the band and the panel set apart,
 * as the limit warnings judge it: the desktop app's in a session the app hosts, the CLI's otherwise. Where it cannot be
 * read whether the app hosts the session, the surface drawing them answers for it, a desktop surface being drawn only
 * in a session the app hosts; the failure is logged.
 */
async function sessionView($: EngineInterface, current: StatusSnapshot, drawnOnDesktop: boolean):
  Promise<{ seen: StatusSnapshot; inUse: StatusAccount | null }> {
  let isDesktopSession = drawnOnDesktop
  try {
    isDesktopSession = await isHostedByDesktop($)
  } catch (error) {
    $.ui.log(`windowtally: desktop hosting not read for the account in use: ${message(error)}`, { to: 'debug' })
  }
  const seen = seenBySession(current, isDesktopSession)
  return { seen, inUse: accountInUse(seen, isDesktopSession) }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // A reload ends a press's work but keeps the session's state: a press left being carried out is forgotten.
    if ((await read($, windowAsk)).isAsking) await update($, windowAsk, () => ({ isAsking: false, said: null }))
    await restoreFold($)
    await refresh($)
    $.clock.every(STATUS_POLL_MS, () => {
      refresh($).catch(error => $.ui.log(`windowtally: status not read: ${message(error)}`, { to: 'debug' }))
    })
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    const result = await next(e)
    if (e.changed.includes('rateLimits') && e.rateLimits.length) await recordSafely($, e.rateLimits)
    return result
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.usage !== undefined) await recordSafely($, (await $.session.usage()).rateLimits)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const current = await read($, snapshot)
    if (current === null) return next(e)
    await read($, minute)
    const now = await $.clock.now()
    const { seen, inUse } = await sessionView($, current, e.surface === 'desktop')
    const onDetails = () => {
      void toggleDetails($)
    }
    if (e.surface === 'desktop') {
      return desktopBandTree($.ui.resolve(e), seen, now, await read($, folded), inUse, onDetails, () => {
        void toggleFold($)
      })
    }
    return bandTree($.ui.resolve(e), seen, now, inUse, onDetails)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const current = await read($, snapshot)
    await read($, minute)
    const ask = await read($, windowAsk)
    const view = current === null ? null : await sessionView($, current, e.surface === 'desktop')
    return panelTree($.ui.resolve(e), e.surface, view?.seen ?? null, await $.clock.now(), view?.inUse ?? null, ask, () => {
      void askWindow($)
    })
  })
}
