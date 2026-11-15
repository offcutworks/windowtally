/**
 * The machine the plugin's tests run on: everything beneath the plugin answered from memory — the environment,
 * the clock, the store, a file system holding WindowTally's data folder, the session and the display.
 *
 * Every account, address and figure here is synthetic.
 */

import type { On, SessionRateLimit } from 'claude-code'
import { expect, mock, type MockClock } from 'claude-code/testing'

export const PLUGIN = 'windowtally'
export const PANE = 'windowtally'
export const HOME = 'C:\\Users\\tester'
export const FOLDER = `${HOME}\\.claude\\windowtally`
export const STATUS = `${FOLDER}\\status.json`
export const MINUTE = 60_000
export const HOUR = 60 * MINUTE
export const DAY = 24 * HOUR
export const T0 = Date.parse('2026-10-21T00:10:00.000Z')
export const ALPHA = 'aaaaaaaa-0000-4000-8000-000000000001'
export const BETA = 'bbbbbbbb-0000-4000-8000-000000000002'

export const iso = (t: number): string => new Date(t).toISOString()

/** What alpha's bills say: Ultra, paid up for another 12 days, this month's plan time worth $193.55 at list price. */
export function subscriptionOf(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    state: 'active', plan: 'ultra', planName: 'Ultra', paidUntil: '2026-11-02', daysLeft: 12, renewSoon: false,
    thisMonthListPrice: 193.55, profilePlan: 'ultra', profileCheck: 'matches',
    ...overrides,
  }
}

/**
 * A version-3 status.json (the contract stated in windowtally/status_file.py): alpha in use by the app and
 * the CLI and recommended, with its bills recorded; beta idle near its weekly cap, with none; this month's totals
 * across the accounts, alpha's plan the only one they sum.
 */
export function statusDoc(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    v: 3,
    generatedAt: iso(T0 - 30_000),
    desktopAccount: ALPHA,
    cliAccount: ALPHA,
    cliCondition: null,
    sourceErrors: [],
    recommended: {
      account: ALPHA, reason: 'alpha has room left and its weekly allowance expires first.', reliefAt: null,
      reliefExact: false,
    },
    renewalReminderDays: null,
    notificationsSilenced: false,
    thisMonth: { apiEquivalent: 1283.56, plansAtListPrice: 193.55 },
    accounts: [
      {
        uuid: BETA, email: 'beta@example.com', label: 'beta', isDesktop: false, isCli: false,
        lastActivity: iso(T0 - 30 * HOUR),
        fiveHour: { state: 'not_started', percent: 0, resetsAt: null, asOf: iso(T0 - 32 * HOUR), estimated: false,
                    exhaustsAt: null },
        weekly: { state: 'current', percent: 96.2, resetsAt: iso(T0 + 3 * DAY + 4 * HOUR), asOf: iso(T0 - 32 * HOUR),
                  estimated: true, exhaustsAt: null, anchorExact: false },
        subscription: null,
      },
      {
        uuid: ALPHA, email: 'alpha@example.com', label: 'alpha', isDesktop: true, isCli: true,
        lastActivity: iso(T0 - MINUTE),
        fiveHour: { state: 'running', percent: 67, resetsAt: iso(T0 + 50 * MINUTE), asOf: iso(T0 - 2 * HOUR),
                    estimated: true, exhaustsAt: null },
        weekly: { state: 'current', percent: 68.5, resetsAt: iso(T0 + 5 * DAY), asOf: iso(T0 - 2 * HOUR),
                  estimated: false, exhaustsAt: null, anchorExact: true },
        subscription: subscriptionOf(),
      },
    ],
    ...overrides,
  }
}

export const BAND_PROPS = {
  hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 200, scroll: { offset: 0, bodyRows: 6 }, view: {},
}

export const PANE_PROPS = {
  title: 'WindowTally', isFocused: false, bodyColumns: 120, placement: 'inline' as const,
  scroll: { offset: 0, bodyRows: 30 }, view: {},
}

/** The usage of a turn that made model requests. */
const USAGE = {
  input_tokens: 10, output_tokens: 20, cache_creation_input_tokens: 0, cache_read_input_tokens: 0,
  model: 'claude-opus-5-5',
}

export type WorldOptions = {
  surfaces?: string[]
  env?: Record<string, string>
  store?: Record<string, unknown>
  /** The test answers `$.store` itself; no store in memory is mocked. */
  ownStore?: boolean
  dataFolder?: boolean
  sessionId?: string
}

export type World = {
  clock: MockClock
  files: Map<string, { text: string; mtimeMs: number }>
  writes: { path: string; text: string }[]
  toasts: string[]
  opened: string[]
  closed: string[]
  setStatus: (doc: unknown, mtimeMs?: number) => void
  setLimits: (limits: SessionRateLimit[]) => void
}

export function world(on: On, options: WorldOptions = {}): World {
  const clock = mock.clock(on, { now: T0 })
  if (!options.ownStore) mock.store(on, options.store ?? {})
  mock.env(on, options.env ?? { USERPROFILE: HOME })
  const files = new Map<string, { text: string; mtimeMs: number }>()
  const folders = new Set<string>(options.dataFolder === false ? [] : [FOLDER])
  const writes: { path: string; text: string }[] = []
  const toasts: string[] = []
  const opened: string[] = []
  const closed: string[] = []
  const panes = new Set<string>()
  const surfaces = options.surfaces ?? ['desktop']
  let limits: SessionRateLimit[] = []
  const missing = (path: string) => ({ deny: `ENOENT: no such file or directory, '${path}'` })

  on('fs.stat', ($, e) => {
    const file = files.get(e.path)
    return file ? { value: { kind: 'file', size: file.text.length, mtimeMs: file.mtimeMs, isLink: false } } : missing(e.path)
  })
  on('fs.read', ($, e) => {
    const file = files.get(e.path)
    return file ? { value: file.text } : missing(e.path)
  })
  on('fs.exists', ($, e) => ({ value: files.has(e.path) || folders.has(e.path) }))
  on('fs.write', ($, e) => {
    files.set(e.path, { text: e.text, mtimeMs: clock.now() })
    writes.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  on('session.id', () => ({ value: options.sessionId ?? 'session-1' }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('session.usage', () => ({ value: { startedAt: T0, context: { window: 1_000_000 }, rateLimits: limits } }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.open', ($, e) => {
    opened.push(e.id)
    panes.add(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.close', ($, e) => {
    closed.push(e.id)
    panes.delete(e.id)
    return { value: undefined }
  })
  on('ui.panes', () => ({
    value: [...panes].map(id => ({ id, title: id, isShown: true, isFocused: false, isPlaced: true })),
  }))
  on('ui.log', () => ({ value: undefined }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.measure', ($, e) => ({ changed: e.changed }))
  on('turn.complete', () => ({ text: '' }))

  return {
    clock, files, writes, toasts, opened, closed,
    setStatus: (doc, mtimeMs = clock.now()) => {
      files.set(STATUS, { text: typeof doc === 'string' ? doc : JSON.stringify(doc), mtimeMs })
    },
    setLimits: next => {
      limits = next
    },
  }
}

/** Starts the session as a host does. */
export function start($: any, surface = 'desktop'): Promise<unknown> {
  return $.session.start({ cwd: HOME, surface, isInteractive: true })
}

/** Ends a main-loop turn; `withRequests` false ends one that made no model request. */
export function endTurn($: any, withRequests = true): Promise<unknown> {
  return $.turn.complete({
    answer: 'done', durationMs: 1000, isAborted: false, turnId: 'turn-1', reason: 'answer',
    ...(withRequests ? { usage: USAGE } : {}),
  })
}

export function limitsOf(fiveHour: number, weekly: number, fiveHourReset = T0 + 3 * HOUR,
                         weeklyReset = T0 + 4 * DAY): SessionRateLimit[] {
  return [
    { kind: 'five_hour', percentUsed: fiveHour, resetsAt: iso(fiveHourReset) },
    { kind: 'seven_day', percentUsed: weekly, resetsAt: iso(weeklyReset) },
  ]
}

/**
 * A weekly reset's weekday and time: they follow the zone the runner reports, and are marked UTC where it reports none
 * but UTC (plugin/hooks/text.ts), so a test matches them by their form.
 */
export const MOMENT = '(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \\d\\d:\\d\\d(?: UTC)?'

/**
 * `text` as a pattern, each `<when>` in it standing for a weekday and time (`MOMENT`), the rest literal; `start` anchors
 * it at the start, `whole` at both ends.
 */
export function withMoments(text: string, anchor: '' | 'start' | 'whole' = ''): RegExp {
  const body = text.split('<when>').map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join(MOMENT)
  return new RegExp(`${anchor ? '^' : ''}${body}${anchor === 'whole' ? '$' : ''}`)
}

/** That `lines` are `texts`, one for one and each whole, a `<when>` in a text standing for a weekday and time. */
export function expectLines(lines: string[], texts: string[]): void {
  expect(lines).toHaveLength(texts.length)
  lines.forEach((line, i) => expect(line).toMatch(withMoments(texts[i]!, 'whole')))
}

/** Every string a drawn tree shows, in order: text children and button labels. */
export function shownText(node: unknown): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(shownText).join('')
  if (typeof node !== 'object' || node === null) return ''
  const element = node as { type?: string; props?: Record<string, unknown>; children?: unknown }
  const label = element.type === 'Button' && typeof element.props?.label === 'string' ? `[${element.props.label}]` : ''
  return shownText(element.children ?? []) + label
}

/** An element of a drawn tree, as a surface receives it. */
export type DrawnNode = { type?: string; props?: Record<string, any>; hover?: Record<string, any>; children?: unknown }

/** An element's child elements, its nested child arrays flattened and its strings left out. */
export function childNodes(node: DrawnNode | undefined): DrawnNode[] {
  const list = Array.isArray(node?.children) ? (node!.children as unknown[]).flat(Infinity) : [node?.children]
  return list.filter((child): child is DrawnNode => typeof child === 'object' && child !== null)
}

/** Every element of the tree, outermost first. */
export function everyNode(node: DrawnNode): DrawnNode[] {
  return [node, ...childNodes(node).flatMap(everyNode)]
}

/** The Box of the tree with the given key. */
export function keyedBox(tree: DrawnNode, key: string): DrawnNode | undefined {
  return everyNode(tree).find(node => node.type === 'Box' && node.props?.key === key)
}

/** The band as `surface` draws it now. */
export async function drawnBand($: any, surface: string): Promise<DrawnNode> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
  const tree = (await ui.drawn()) as DrawnNode
  await ui.unmount()
  return tree
}

/** The panel as the desktop draws it now. */
export async function drawnPanel($: any): Promise<DrawnNode> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const tree = (await ui.drawn()) as DrawnNode
  await ui.unmount()
  return tree
}
