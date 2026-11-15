/**
 * Accounts whose bills record a plan that has ended and none since (status.json's subscription state `ended`). The
 * band tags such an account `plan ended` where the renewal tag stands; one that neither client uses shows no windows
 * on any band surface — it takes no readings, so its figures are its last ones rolled forward through their resets to
 * nothing — only its week's reset, its tag dim; one a client uses keeps its windows, its tag in the warning colour. A
 * plan upcoming or no bill recorded is drawn as before. The panel's one line for such an account is setaside.test.tsx's.
 * What the desktop app paints is checked by eye; here the trees are read as the surfaces receive them; `<when>` is a
 * weekly reset's weekday and time (`withMoments`).
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BAND_PROPS, BETA, HOUR, PANE, PANE_PROPS, PLUGIN, T0, expectLines, iso, shownText, start, statusDoc,
  subscriptionOf, withMoments, world,
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

function keyed(tree: Node, key: string): Node {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === key)!
}

const NOT_STARTED = { state: 'not_started', percent: 0, resetsAt: null, asOf: iso(T0 - 40 * 24 * HOUR), estimated: false,
                      exhaustsAt: null }

/**
 * The status with gamma after the two the world's status lists: idle, its last reading forty days old and its week
 * rolled forward to nothing, with the subscription `gamma` and the 5-hour window `fiveHour`; `changes` amend the
 * document.
 */
function withGamma(gamma: Record<string, unknown> | null, changes: Record<string, unknown> = {},
                   fiveHour: Record<string, unknown> = NOT_STARTED): Record<string, unknown> {
  const doc = statusDoc(changes)
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts.push({
    uuid: GAMMA, email: 'gamma@example.com', label: 'gamma', isDesktop: false, isCli: false, lastActivity: null,
    fiveHour,
    weekly: { state: 'current', percent: 0, resetsAt: iso(T0 + 2 * 24 * HOUR), asOf: iso(T0 - 40 * 24 * HOUR),
              estimated: false, exhaustsAt: null, anchorExact: true },
    subscription: gamma,
  })
  return doc
}

const ENDED = subscriptionOf({ state: 'ended', plan: null, planName: null, paidUntil: '2026-09-10', daysLeft: null })

async function drawn($: any, surface: string, component = 'AbovePrompt'): Promise<Node> {
  const ui = component === 'Pane'
    ? await $.ui.mount({ plugin: PLUGIN, surface, component, requestId: PANE, props: PANE_PROPS })
    : await $.ui.mount({ plugin: PLUGIN, surface, component, props: BAND_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

test('an ended plan no client uses shows its tag, dim, and its week\'s reset in place of its windows, on both bands',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withGamma(ENDED))
    await start($)
    const desktop = await drawn($, 'desktop')
    expect(shownText(keyed(desktop, 'others')))
      .toMatch(withMoments('● beta 5h – week ≈96% ↻<when>│ gamma plan ended week ↻<when>', 'whole'))
    const tag = walk(desktop).find(node => node.type === 'Text' && shownText(node) === ' plan ended')!
    expect([tag.props?.color, tag.props?.dimColor]).toEqual([undefined, true])
    const terminal = shownText(await drawn($, 'terminal'))
    expect(terminal).toMatch(withMoments('beta  5h not started  week ≈96% ↻<when>  │  gamma plan ended  week ↻<when>[Details]'))
  })

test('an ended plan with no 5-hour limit shows its tag and its week\'s reset alike, its weekly window leading none',
  async ($, on) => {
    const w = world(on)
    const noLimit = { state: 'no_limit', percent: null, resetsAt: null, asOf: iso(T0 - 40 * 24 * HOUR), estimated: false,
                      exhaustsAt: null }
    w.setStatus(withGamma(ENDED, {}, noLimit))
    await start($)
    expect(shownText(keyed(await drawn($, 'desktop'), 'others')))
      .toMatch(withMoments('● beta 5h – week ≈96% ↻<when>│ gamma plan ended week ↻<when>', 'whole'))
    expect(shownText(await drawn($, 'terminal'))).toMatch(withMoments('│  gamma plan ended  week ↻<when>[Details]'))
  })

test('the tag agrees with the windows left out, though a file also marks the plan due to renew', async ($, on) => {
  const w = world(on)
  w.setStatus(withGamma({ ...ENDED, renewSoon: true, daysLeft: 0 }))
  await start($)
  const others = shownText(keyed(await drawn($, 'desktop'), 'others'))
  expect(others).toMatch(withMoments('● beta 5h – week ≈96% ↻<when>│ gamma plan ended week ↻<when>', 'whole'))
})

test('folded, the line and the card show an ended plan no client uses by its name, tag and week\'s reset alone',
  async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(withGamma(ENDED))
  await start($)
  const band = await drawn($, 'desktop')
  const accounts = keyed(band, 'folded-accounts')
  const line = walk(accounts).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end')!
  expect(shownText(line)).toMatch(withMoments('beta 5h – week ≈96% ↻<when> │ gamma plan ended week ↻<when>', 'whole'))
  const tag = children(line).find((run): run is Node => typeof run === 'object' && run !== null
                                                         && shownText(run) === ' plan ended')!
  expect(tag.props?.wrap).toBe('truncate-end')
  expect([tag.props?.color, tag.props?.dimColor]).toEqual([undefined, true])
  const card = walk(band).find(node => node.type === 'Box' && node.props?.position === 'absolute')!
  const blocks = children(card).filter((block): block is Node => typeof block === 'object' && block !== null)
  expectLines(blocks.map(shownText), [
    'alpha (app, CLI, next)5h ≈67% ↻50m week 69% ↻<when>', 'beta5h – week ≈96% ↻<when>', 'gamma plan endedweek ↻<when>',
  ])
  const parts = children(blocks[2]!).filter((part): part is Node => typeof part === 'object' && part !== null)
  expectLines(parts.map(shownText), ['gamma plan ended', 'week ↻<when>'])   // its name and tag, its week's reset: no figure
})

test('an ended plan a client uses keeps its windows, the tag beside its name', async ($, on) => {
  const w = world(on)
  const doc = withGamma(subscriptionOf(), {
    recommended: { account: BETA, reason: 'beta has room left.', reliefAt: null, reliefExact: false },
  })
  const alpha = (doc.accounts as Array<Record<string, any>>).find(account => account.uuid === ALPHA)!
  alpha.subscription = ENDED
  w.setStatus(doc)
  await start($)
  const inUse = shownText(keyed(await drawn($, 'desktop'), 'in-use'))
  expect(inUse).toContain('● alpha (app, CLI) plan ended')
  expect(inUse).toContain('5h≈67%↻50m')
  expect(inUse).toMatch(withMoments('week69%↻<when>'))
  const terminal = shownText(await drawn($, 'terminal'))
  expect(terminal).toMatch(withMoments('alpha (app, CLI) plan ended  5h ≈67% ↻50m  week 69% ↻<when>'))
  const tag = walk(await drawn($, 'desktop')).find(node => node.type === 'Text' && shownText(node) === ' plan ended')!
  expect(tag.props?.color).toBe('warning')
})

const NOT_ENDED: Array<[string, Record<string, unknown> | null]> = [
  ['upcoming', subscriptionOf({ state: 'upcoming', plan: null, planName: null, paidUntil: '2026-10-25',
                                daysLeft: null })],
  ['active', subscriptionOf()],
  ['with no bill recorded', subscriptionOf({ state: 'none', plan: null, planName: null, paidUntil: null,
                                             daysLeft: null })],
  ['with no bill source', null],
]

for (const [name, gamma] of NOT_ENDED) {
  test(`a plan ${name} no client uses is drawn with its windows and no tag`, async ($, on) => {
    const w = world(on)
    w.setStatus(withGamma(gamma))
    await start($)
    const others = shownText(keyed(await drawn($, 'desktop'), 'others'))
    expect(others).toMatch(withMoments('● beta 5h – week ≈96% ↻<when>│ gamma 5h – week 0% ↻<when>', 'whole'))
  })
}
