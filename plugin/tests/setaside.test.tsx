/**
 * A weekly reset read by its weekday, and an account whose plan has ended set aside. The weekly window's reset is
 * written by its weekday and time (`↻Sat 04:00`) on every band surface and in the panel, the 5-hour window's by the
 * time left. An account whose plan has ended and that no client uses shows no figures but its week's reset, its
 * `plan ended` dim rather than a warning, and the panel gives it one dim line. Weekday and time follow the zone the
 * runner reports, so they are matched by their form.
 */

import { expect, test } from 'claude-code/testing'
import {
  BAND_PROPS, DAY, HOUR, MOMENT, PANE, PANE_PROPS, PLUGIN, T0, iso, shownText, start, statusDoc, subscriptionOf, world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown[] }

const GAMMA = 'cccccccc-0000-4000-8000-000000000003'

function walk(node: Node): Node[] {
  const nested = (Array.isArray(node.children) ? node.children.flat(Infinity) : [])
    .filter((child): child is Node => typeof child === 'object' && child !== null)
  return [node, ...nested.flatMap(walk)]
}

function keyed(tree: Node, key: string): Node {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === key)!
}

/** The world's status with gamma last: its plan ended on 10 Sep, idle, its week rolled forward to nothing. */
function withEndedGamma(): Record<string, unknown> {
  const doc = statusDoc()
  ;(doc.accounts as Array<Record<string, unknown>>).push({
    uuid: GAMMA, email: 'gamma@example.com', label: 'gamma', isDesktop: false, isCli: false, lastActivity: null,
    fiveHour: { state: 'not_started', percent: 0, resetsAt: null, asOf: iso(T0 - 40 * DAY), estimated: false,
                exhaustsAt: null },
    weekly: { state: 'current', percent: 0, resetsAt: iso(T0 + 2 * DAY), asOf: iso(T0 - 40 * DAY), estimated: false,
              exhaustsAt: null, anchorExact: true },
    subscription: subscriptionOf({ state: 'ended', plan: null, planName: null, paidUntil: '2026-09-10',
                                   daysLeft: null }),
  })
  return doc
}

async function drawn($: any, surface: string, component = 'AbovePrompt'): Promise<Node> {
  const ui = component === 'Pane'
    ? await $.ui.mount({ plugin: PLUGIN, surface, component, requestId: PANE, props: PANE_PROPS })
    : await $.ui.mount({ plugin: PLUGIN, surface, component, props: BAND_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

test('the weekly reset reads by weekday and time on both bands, the 5-hour one by the time left', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const inUse = shownText(keyed(await drawn($, 'desktop'), 'in-use'))
  expect(inUse).toContain('5h≈67%↻50m')
  expect(inUse).toMatch(new RegExp(`week69%↻${MOMENT}`))
  const terminal = shownText(await drawn($, 'terminal'))
  expect(terminal).toMatch(new RegExp(`alpha \\(app, CLI, next\\)  5h ≈67% ↻50m  week 69% ↻${MOMENT}`))
  expect(terminal).not.toContain('↻5d 0h')
})

test('an ended plan no client uses keeps only its week\'s reset, its tag dim', async ($, on) => {
  const w = world(on)
  w.setStatus(withEndedGamma())
  await start($)
  const desktop = await drawn($, 'desktop')
  expect(shownText(keyed(desktop, 'others'))).toMatch(new RegExp(`│ gamma plan ended week ↻${MOMENT}$`))
  const tag = walk(desktop).find(node => node.type === 'Text' && shownText(node) === ' plan ended')!
  expect(tag.props?.dimColor).toBe(true)
  expect(tag.props?.color).toBeUndefined()
  expect(shownText(await drawn($, 'terminal'))).toMatch(new RegExp(`│  gamma plan ended  week ↻${MOMENT}`))
})

test('the panel gives an ended plan no client uses one dim line and no figures', async ($, on) => {
  const w = world(on)
  w.setStatus(withEndedGamma())
  await start($)
  const panel = shownText(await drawn($, 'desktop', 'Pane'))
  const gamma = panel.slice(panel.indexOf('gamma'), panel.indexOf('Updated'))
  expect(gamma).toMatch(new RegExp(`^gammaplan ended Thu 10 Sep · week resets ${MOMENT}$`))   // the window's month
})

test('the panel says the weekly reset by weekday with the time left beside it, and drops what it repeats',
  async ($, on) => {
    const w = world(on)
    w.setStatus(statusDoc())
    await start($)
    const panel = shownText(await drawn($, 'desktop', 'Pane'))
    expect(panel).toMatch(new RegExp(`↻${MOMENT}in 5d 0h`))
    expect(panel).not.toContain('alpha@example.com')
    expect(panel).not.toContain('exact reset time')
    expect(panel).not.toContain('at list price')
    expect(panel).not.toContain('No source problems')
    expect(panel).toContain('Updated just now.')
    expect(panel).toContain('[Open WindowTally]')
  })

test('a weekly reset more than six days off carries its date, so it never reads as today\'s', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  const alpha = (doc.accounts as Array<Record<string, any>>)[1]!
  alpha.weekly = { ...alpha.weekly, resetsAt: iso(T0 + 6 * DAY + 18 * HOUR) }
  w.setStatus(doc)
  await start($)
  const terminal = shownText(await drawn($, 'terminal'))
  expect(terminal).toMatch(/week 69% ↻(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2,3} \d\d:\d\d/)
})

test('the time left the panel adds is marked ≈ where the moment was inferred', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    recommended: { account: null, reason: 'Every account is at its limit. The first opens ≈Wed 03:10.',
                   reliefAt: iso(T0 + 3 * HOUR), reliefExact: false },
  }))
  await start($)
  expect(shownText(await drawn($, 'desktop', 'Pane'))).toContain('The first opens ≈Wed 03:10 (in ≈3h 00m).')
})

test('the panel adds the time left to the moment the reason names, once', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    recommended: { account: null, reason: 'Every account is at its limit. The first opens Wed 03:10.',
                   reliefAt: iso(T0 + 3 * HOUR), reliefExact: true },
  }))
  await start($)
  const panel = shownText(await drawn($, 'desktop', 'Pane'))
  expect(panel).toContain('Next: Every account is at its limit. The first opens Wed 03:10 (in 3h 00m).')
  expect(panel).not.toContain('opens in')
})
