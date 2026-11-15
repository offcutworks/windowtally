/**
 * Accounts the user hid, and the folded desktop band's one line. status.json marks `hidden` an account the user hid
 * that neither client uses: no line of the band, no card and no block of the panel shows it, and the panel's foot says
 * how many are hidden and where they are shown again. Folded, every run of the accounts' line is a Text cut rather than
 * wrapped, so the desktop app keeps the line whole; unfolded, the runs wrap as before. What the desktop app paints is
 * checked by eye; here the trees are read as the surfaces receive them.
 */

import { expect, test } from 'claude-code/testing'
import {
  BAND_PROPS, HOUR, PANE, PANE_PROPS, PLUGIN, T0, iso, shownText, start, statusDoc, subscriptionOf, withMoments,
  world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown[] }

const FOLDED_KEY = 'bandFolded'
const GAMMA = 'cccccccc-0000-4000-8000-000000000003'

function children(node: Node): unknown[] {
  return Array.isArray(node.children) ? node.children.flat(Infinity) : []
}

function walk(node: Node): Node[] {
  const nested = children(node).filter((child): child is Node => typeof child === 'object' && child !== null)
  return [node, ...nested.flatMap(walk)]
}

/** The status with gamma, idle and hidden by the user, after the two the world's status lists. */
function withGamma(hidden: boolean, beta: Record<string, unknown> = {}): Record<string, unknown> {
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  Object.assign(accounts[0]!, beta)
  const gamma: Record<string, unknown> = {
    uuid: GAMMA, email: 'gamma@example.com', label: 'gamma', isDesktop: false, isCli: false, lastActivity: null,
    fiveHour: { state: 'not_started', percent: 0, resetsAt: null, asOf: iso(T0 - 40 * 24 * HOUR), estimated: false,
                exhaustsAt: null },
    weekly: { state: 'current', percent: 0, resetsAt: iso(T0 + 2 * 24 * HOUR), asOf: iso(T0 - 40 * 24 * HOUR),
              estimated: false, exhaustsAt: null, anchorExact: true },
    subscription: subscriptionOf({ state: 'ended', plan: null, planName: null, paidUntil: '2026-09-10',
                                   daysLeft: null }),
  }
  if (hidden) gamma.hidden = true
  accounts.push(gamma)
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

test('a hidden account is on no line of the band, on either surface, nor in the panel', async ($, on) => {
  const w = world(on)
  w.setStatus(withGamma(true))
  await start($)
  for (const surface of ['terminal', 'desktop']) {
    const band = shownText(await drawn($, surface))
    expect(band).toContain('alpha')
    expect(band).toContain('beta')
    expect(band).not.toContain('gamma')
  }
  const panel = shownText(await drawn($, 'desktop', 'Pane'))
  expect(panel).toContain('beta')
  expect(panel).not.toContain('gamma')
  expect(panel).toContain('1 account hidden: Arrange accounts… in the WindowTally window shows it.')
})

test('an account listed is shown wherever it was, and the panel says nothing of hidden accounts', async ($, on) => {
  const w = world(on)
  w.setStatus(withGamma(false))
  await start($)
  expect(shownText(await drawn($, 'desktop'))).toContain('gamma plan ended')
  const panel = shownText(await drawn($, 'desktop', 'Pane'))
  expect(panel).toContain('gamma')
  expect(panel).not.toContain('hidden')
})

test('folded, a hidden account is neither on the line nor in the card the button reveals', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(withGamma(true))
  await start($)
  const band = await drawn($, 'desktop')
  const card = walk(band).find(node => node.type === 'Box' && node.props?.position === 'absolute')!
  expect(shownText(card)).toContain('beta')
  expect(shownText(band)).not.toContain('gamma')
})

test('folded, every run of the accounts\' line is a Text cut at its end, so the line never wraps', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(withGamma(false, { subscription: subscriptionOf({ daysLeft: 1, renewSoon: true }) }))
  await start($)
  const band = await drawn($, 'desktop')
  const accounts = walk(band).find(node => node.type === 'Box' && node.props?.key === 'folded-accounts')!
  const line = walk(accounts).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end')!
  expect(shownText(line))
    .toMatch(withMoments('beta renew 1d 5h – week ≈96% ↻<when> │ gamma plan ended week ↻<when>', 'whole'))
  const runs = children(line)
  expect(runs.filter(run => typeof run === 'string' && run !== '')).toEqual([])
  const texts = runs.filter((run): run is Node => typeof run === 'object' && run !== null)
  expect(texts.length).toBeGreaterThan(10)
  expect(texts.every(run => run.type === 'Text' && run.props?.wrap === 'truncate-end')).toBe(true)
  expect(texts.find(run => shownText(run) === ' renew 1d')?.props?.color).toBe('warning')
  expect(texts.find(run => shownText(run) === '≈96%')?.props?.color).toBe('error')
})

test('unfolded, the other accounts\' runs wrap as before, none of them cut', async ($, on) => {
  const w = world(on)
  w.setStatus(withGamma(false, { subscription: subscriptionOf({ daysLeft: 1, renewSoon: true }) }))
  await start($)
  const band = await drawn($, 'desktop')
  const others = walk(band).find(node => node.type === 'Box' && node.props?.key === 'others')!
  expect(walk(others).filter(node => node.type === 'Text' && node.props?.wrap !== undefined)).toEqual([])
  const terminal = await drawn($, 'terminal')
  const cut = walk(terminal).filter(node => node.type === 'Text' && node.props?.wrap === 'truncate-end')
  expect(cut).toHaveLength(1)
  expect(walk(cut[0]!).slice(1).filter(node => node.type === 'Text' && node.props?.wrap !== undefined)).toEqual([])
})
