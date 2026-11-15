/**
 * Which windows the band draws: an account with no 5-hour limit (status.json's 5-hour state `no_limit`) shows no
 * 5-hour window on any band surface — the terminal's line, the desktop's in-use line, the others' line, the folded line
 * and the folded button's card — its weekly window leading as before, while the panel still says `no limit`; and a
 * per-model window (Fable's) shows its figure alone on the band, with no meter, where the weekly and 5-hour windows keep
 * theirs. Read as each surface receives the tree; what the desktop app paints is checked by eye.
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BETA, HOUR, T0, drawnBand as band, drawnPanel as panel, everyNode as walk, iso, keyedBox as keyed, shownText,
  start, statusDoc, withMoments, world, type DrawnNode as Node,
} from './world'

const NO_LIMIT = {
  state: 'no_limit', percent: null, resetsAt: null, asOf: iso(T0 - 2 * HOUR), estimated: false, exhaustsAt: null,
  anchorExact: false,
}

const FOLDED_KEY = 'bandFolded'

function meters(node: Node): Node[] {
  return walk(node).filter(n => n.type === 'Svg')
}

/** The world's document with the given accounts' 5-hour windows removed. */
function withoutLimit(doc: Record<string, unknown>, ...uuids: string[]): Record<string, unknown> {
  for (const account of doc.accounts as Array<Record<string, any>>) {
    if (uuids.includes(account.uuid)) account.fiveHour = { ...NO_LIMIT }
  }
  return doc
}

/** The world's document, alpha's weekly window carrying Fable's at `percent`, resetting with the week. */
function withFable(percent: number, doc: Record<string, unknown> = statusDoc()): Record<string, unknown> {
  const alpha = (doc.accounts as Record<string, any>[]).find(account => account.uuid === ALPHA)!
  alpha.weekly.scoped = [{
    name: 'Fable', state: 'current', percent, resetsAt: alpha.weekly.resetsAt, asOf: iso(T0 - 3 * HOUR),
    estimated: true, allowanceOfWeekly: 50,
  }]
  return doc
}

test('the terminal band shows no 5-hour window for an account with no 5-hour limit, its week leading', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(withoutLimit(statusDoc(), ALPHA, BETA))
  await start($, 'terminal')
  const shown = shownText(await band($, 'terminal'))
  expect(shown).toMatch(withMoments('alpha (app, CLI, next)  week 69% ↻<when>  │  beta  week ≈96% ↻<when>[Details]'))
  expect(shown).not.toContain('5h')
  expect(shown).not.toContain('no limit')
})

test('the desktop\'s in-use line shows the week alone at the 5-hour scale, with its one meter', async ($, on) => {
  const w = world(on)
  w.setStatus(withoutLimit(statusDoc(), ALPHA))
  await start($)
  const inUse = keyed(await band($, 'desktop'), 'in-use')!
  expect(shownText(inUse)).toMatch(withMoments('● alpha (app, CLI, next)week69%↻<when>', 'whole'))
  expect(meters(inUse).map(m => [m.props?.alt, m.props?.width])).toEqual([['weekly window 69% used', 72]])
})

test('the others\' line shows no 5-hour window for an account with no 5-hour limit', async ($, on) => {
  const w = world(on)
  w.setStatus(withoutLimit(statusDoc(), BETA))
  await start($)
  const others = shownText(keyed(await band($, 'desktop'), 'others')!)
  expect(others).toMatch(withMoments('● beta week ≈96% ↻<when>', 'whole'))
})

test('folded, neither the line nor the button\'s card shows a 5-hour window for an account with no 5-hour limit',
  async ($, on) => {
    const w = world(on, { store: { [FOLDED_KEY]: true } })
    w.setStatus(withoutLimit(statusDoc(), ALPHA, BETA))
    await start($)
    const tree = await band($, 'desktop')
    expect(shownText(keyed(tree, 'folded-accounts')!)).toMatch(withMoments('● beta week ≈96% ↻<when>', 'whole'))
    const card = walk(keyed(tree, 'fold-tag')!).find(node => node.type === 'Box' && node.props?.position === 'absolute')!
    expect(shownText(card)).toMatch(withMoments('alpha (app, CLI, next)week 69% ↻<when>betaweek ≈96% ↻<when>', 'whole'))
  })

test('the panel still says the account has no 5-hour limit', async ($, on) => {
  const w = world(on)
  w.setStatus(withoutLimit(statusDoc(), ALPHA))
  await start($)
  const alpha = keyed(await panel($), `account-${ALPHA}`)!
  expect(shownText(alpha)).toContain('no limit')
})

test('on the in-use line Fable\'s window shows its figure and no meter, the 5-hour and weekly windows keeping theirs',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withFable(24.1))
    await start($)
    const inUse = keyed(await band($, 'desktop'), 'in-use')!
    expect(shownText(inUse)).toMatch(withMoments('● alpha (app, CLI, next)5h≈67%↻50mweek69%↻<when>Fable≈24%', 'whole'))
    expect(meters(inUse).map(m => m.props?.alt)).toEqual(['5-hour window ≈67% used', 'weekly window 69% used'])
  })

test('Fable\'s figure keeps its warning colours with no meter', async ($, on) => {
  const w = world(on)
  w.setStatus(withFable(96))
  await start($)
  const inUse = keyed(await band($, 'desktop'), 'in-use')!
  const figure = walk(inUse).filter(n => n.type === 'Text' && shownText(n) === '≈96%').pop()
  expect(figure?.props?.color).toBe('error')
  expect(meters(inUse)).toHaveLength(2)
})

test('with no 5-hour limit and Fable\'s window the in-use line is the week, then Fable\'s figure, one meter',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withFable(24.1, withoutLimit(statusDoc(), ALPHA)))
    await start($)
    const inUse = keyed(await band($, 'desktop'), 'in-use')!
    expect(shownText(inUse)).toMatch(withMoments('● alpha (app, CLI, next)week69%↻<when>Fable≈24%', 'whole'))
    expect(meters(inUse).map(m => m.props?.alt)).toEqual(['weekly window 69% used'])
  })
