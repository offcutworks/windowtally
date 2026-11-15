/**
 * The desktop band's lines, its fold — the fold button, what a fold hides and keeps, its memory in the plugin's store —
 * the card the folded button reveals, and the ≈ a reset time takes on the band and the panel. Unfolded, the account in
 * use stands on a line of its own and the others follow as units of their own, beside the fold button over Details;
 * folded, the band is one line: the button, the other accounts — or, with none, the account in use — cut at the band's
 * edge, then the fault flags. What the desktop app paints from these trees is checked by eye; here the trees are read
 * as the desktop surface receives them.
 */

import { expect, test } from 'claude-code/testing'
import {
  BAND_PROPS, HOUR, MINUTE, PANE, PANE_PROPS, PLUGIN, T0, expectLines, iso, shownText, start, statusDoc, withMoments,
  world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; hover?: Record<string, any>; children?: unknown[] }

const FOLDED_KEY = 'bandFolded'
/** alpha's line on the terminal, in the full words; `<when>` is a weekly reset's weekday and time (`withMoments`). */
const ALPHA_LINE = 'alpha (app, CLI, next)  5h ≈67% ↻50m  week 69% ↻<when>'
/** alpha, the account in use, on its line of the desktop band: a group each for its name, its 5-hour and its weekly window. */
const ALPHA_IN_USE = '● alpha (app, CLI, next)5h≈67%↻50mweek69%↻<when>'
/** beta's unit on the others' line, in the compact words; a unit after the first opens with `│ `. */
const BETA_UNIT = 'beta 5h – week ≈96% ↻<when>'

function elements(node: unknown): Node[] {
  return (Array.isArray(node) ? node : [node]).flatMap(child =>
    typeof child === 'object' && child !== null ? [child as Node] : [])
}

function children(node: Node): Node[] {
  return elements(node.children ?? [])
}

/** Every element of the tree, outermost first. */
function walk(node: Node): Node[] {
  return [node, ...children(node).flatMap(walk)]
}

async function desktopBand($: any): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'AbovePrompt', props: BAND_PROPS })
  const drawn = (await ui.drawn()) as Node
  await ui.unmount()
  return drawn
}

async function pressOnDesktop($: any, key: string): Promise<void> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'AbovePrompt', props: BAND_PROPS })
  await ui.press({ key })
  await ui.unmount()
}

/** The area of the folded desktop band the units wrap in: the fold button and the fault flags. */
function area(band: Node): Node | undefined {
  return children(band).find(child => child.props?.key === 'units')
}

/** The Box of the tree with the given key. */
function keyed(tree: Node, key: string): Node | undefined {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === key)
}

function card(tree: Node): Node | undefined {
  return walk(tree).find(node => node.type === 'Box' && node.props?.position === 'absolute')
}

test('on the desktop the account in use has a line of its own, each other account a unit of its own, Details under the fold button', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  ;(doc.accounts as Array<Record<string, any>>).push({
    ...(doc.accounts as Array<Record<string, any>>)[0], uuid: 'cccccccc-0000-4000-8000-000000000003',
    email: 'gamma@example.com', label: 'gamma',
  })
  w.setStatus(doc)
  await start($)
  const band = await desktopBand($)
  expect(band.type).toBe('Box')
  expect(band.props?.flexDirection).toBe('row')
  const accounts = keyed(band, 'accounts')!
  const inUse = keyed(band, 'in-use')!
  const units = keyed(band, 'others-units')!
  expect(units.props?.flexWrap).toBe('wrap')
  // The desktop app reshapes a row whose last children are buttons; no row of the band holds one of its own.
  for (const holder of [band, accounts, inUse, units]) expect(children(holder).some(child => child.type === 'Button')).toBe(false)
  expect(shownText(inUse)).toMatch(withMoments(ALPHA_IN_USE, 'whole'))
  const row = children(units)
  expectLines(row.map(unit => shownText(unit)), [BETA_UNIT, `│ ${BETA_UNIT.replace('beta', 'gamma')}`])
  expect(row.every(unit => unit.props?.flexShrink === 1)).toBe(true)
  expect(children(accounts).map(line => line.props?.key)).toEqual(['in-use', 'others'])
  const controls = keyed(band, 'controls')!
  expect(children(band)[0]).toBe(controls)
  const last = children(controls)[children(controls).length - 1]!
  expect(last.props?.flexShrink).toBe(0)
  expect(shownText(last)).toBe('[Details]')
})

test('on the desktop the fault flags stand as groups of their own after the account in use', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    generatedAt: iso(T0 - 10 * MINUTE),
    sourceErrors: ['transcripts: disk unreadable'],
    recommended: {
      account: null, reason: 'Every account is at its limit.', reliefAt: iso(T0 + 2 * HOUR), reliefExact: true,
    },
  }))
  await start($)
  const row = children(keyed(await desktopBand($), 'in-use')!)
  const weekly = row.findIndex(child => shownText(child).startsWith('week'))
  for (const flag of ['all accounts at their limit · first opens ↻2h 00m', 'status 10m old', '1 source problem']) {
    const holder = row.find(child => shownText(child) === flag)
    expect(holder?.props?.flexShrink).toBe(1)
    expect(row.indexOf(holder!)).toBeGreaterThan(weekly)
  }
})

test('the fold button folds the desktop band to itself, the other accounts and the fault flags, and unfolds it again',
  async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({ sourceErrors: ['transcripts: disk unreadable'] }))
  await start($)
  expect(shownText(await desktopBand($))).toContain('[Accounts ▾]')
  await pressOnDesktop($, 'fold')
  const folded = await desktopBand($)
  const shown = shownText(children(area(folded)!).filter(child => child.props?.key !== 'fold-tag'))
  expect(shown).toMatch(withMoments(`● ${BETA_UNIT}│ 1 source problem`, 'whole'))
  expect(shownText(folded)).toContain('[Accounts ▸]')
  expect(shownText(folded)).not.toContain('[Details]')
  await pressOnDesktop($, 'fold')
  const unfolded = await desktopBand($)
  expect(shownText(unfolded)).toMatch(withMoments(ALPHA_IN_USE))
  expect(shownText(unfolded)).toContain('[Details]')
})

test('the fold is kept in the store, and a session starts as the last fold left the band', async ($, on) => {
  let stored: unknown
  on('store.get', ($, e) => ({ value: e.key === FOLDED_KEY ? stored : undefined }))
  on('store.set', ($, e) => {
    if (e.key === FOLDED_KEY) stored = e.value
    return { value: undefined }
  })
  const w = world(on, { ownStore: true })
  w.setStatus(statusDoc())
  await start($)
  await pressOnDesktop($, 'fold')
  expect(stored).toBe(true)
  await pressOnDesktop($, 'fold')
  expect(stored).toBe(false)
})

test('a store that cannot be read or written costs the fold\'s memory, never the band', async ($, on) => {
  on('store.get', () => ({ deny: 'the store cannot be read' }))
  on('store.set', () => ({ deny: 'the store cannot be written' }))
  const w = world(on, { ownStore: true })
  w.setStatus(statusDoc())
  await start($)
  expect(shownText(await desktopBand($))).toMatch(withMoments(ALPHA_IN_USE))
  await pressOnDesktop($, 'fold')
  expect(shownText(await desktopBand($))).toContain('[Accounts ▸]')
})

test('a session whose store holds the fold starts folded, the other accounts beside the button', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(statusDoc())
  await start($)
  const band = await desktopBand($)
  expect(shownText(band)).toContain('[Accounts ▸]')
  expect(shownText(children(area(band)!).filter(child => child.props?.key !== 'fold-tag')))
    .toMatch(withMoments(`● ${BETA_UNIT}`, 'whole'))
})

test('folded, the tag holds a card of every account that a pointer resting on it reveals', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(statusDoc())
  await start($)
  const band = await desktopBand($)
  const tag = children(area(band)!).find(child => child.props?.key === 'fold-tag')
  expect(tag?.type).toBe('Box')
  const found = card(tag!)
  expect(found).toBeDefined()
  expect(found!.props?.display).toBe('none')
  expect(found!.hover?.display).toBe('flex')
  const text = shownText(found)
  expect(text).toContain('alpha (app, CLI, next)')
  expect(text).toMatch(withMoments('5h ≈67% ↻50m week 69% ↻<when>'))
  expect(text).toContain('beta')
  expect(text).toMatch(withMoments('5h – week ≈96% ↻<when>'))
  expect(text.indexOf('alpha')).toBeLessThan(text.indexOf('beta'))
})

test('folded, the band is the button, the other accounts cut at its edge in the room left, then the fault flags', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(statusDoc({ sourceErrors: ['transcripts: disk unreadable'] }))
  await start($)
  const band = await desktopBand($)
  const line = area(band)!
  expect(line.props?.flexWrap).toBe('wrap')
  expect(children(line).map(child => child.props?.key)).toEqual(['fold-tag', 'folded-accounts', undefined])
  const accounts = keyed(band, 'folded-accounts')!
  // It asks for no width, so it never moves a unit to a further line, and grows into the room the others leave.
  expect([accounts.props?.width, accounts.props?.flexGrow, accounts.props?.minWidth]).toEqual([0, 1, 0])
  // The account in use is left to Claude's own usage indicator; the others take the line, behind a grey dot.
  expect(shownText(accounts)).toMatch(withMoments(`● ${BETA_UNIT}`, 'whole'))
  expect(walk(accounts).find(node => node.type === 'Text')?.props?.dimColor).toBe(true)
  const cut = walk(accounts).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end')
  expect(cut?.props?.size).toBe('footnote')
  const holder = walk(accounts).find(node => node.type === 'Box' && children(node).includes(cut!))!
  expect([holder.props?.flexShrink, holder.props?.minWidth, holder.props?.overflow]).toEqual([1, 0, 'hidden'])
  const flag = children(line)[2]!
  expect(shownText(flag)).toBe('│ 1 source problem')
  expect(flag.props?.flexShrink).toBe(0)
  expect(shownText(band)).not.toContain('[Details]')
  expect(card(band)).toBeDefined()
})

test('folded, every fault flag after the accounts opens with the separator and never shrinks', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(statusDoc({
    generatedAt: iso(T0 - 10 * MINUTE),
    sourceErrors: ['transcripts: disk unreadable'],
    recommended: {
      account: null, reason: 'Every account is at its limit.', reliefAt: iso(T0 + 2 * HOUR), reliefExact: true,
    },
  }))
  await start($)
  const flags = children(area(await desktopBand($))!).slice(2)
  expect(flags.map(flag => shownText(flag))).toEqual([
    '│ all accounts at their limit · first opens ↻2h 00m', '│ status 10m old', '│ 1 source problem',
  ])
  expect(flags.every(flag => flag.props?.flexShrink === 0)).toBe(true)
})

test('folded, the other accounts follow one another on the line, and with no account in use every account does', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  const doc = statusDoc({ desktopAccount: null, desktopSignedIn: false })
  ;(doc.accounts as Array<Record<string, any>>)[1]!.isDesktop = false
  w.setStatus(doc)
  await start($)
  const accounts = keyed(await desktopBand($), 'folded-accounts')!
  expect(shownText(accounts))
    .toMatch(withMoments(`● alpha (CLI, next) 5h ≈67% ↻50m week 69% ↻<when> │ ${BETA_UNIT}`, 'whole'))
  expect(walk(accounts).find(node => node.type === 'Text')?.props?.color).toBeUndefined()
})

test('folded with no other account, the account in use takes the line, its dot orange', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  const doc = statusDoc()
  doc.accounts = (doc.accounts as Array<Record<string, any>>).filter(account => account.label === 'alpha')
  w.setStatus(doc)
  await start($)
  const band = await desktopBand($)
  const accounts = keyed(band, 'folded-accounts')!
  expect(shownText(accounts)).toMatch(withMoments('● alpha (app, CLI, next) 5h ≈67% ↻50m week 69% ↻<when>', 'whole'))
  expect(walk(accounts).find(node => node.type === 'Text')?.props?.color).toBe('claude')
  expect(children(area(band)!)).toHaveLength(2)
})

test('unfolded, the band carries no card', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  expect(card(await desktopBand($))).toBeUndefined()
})

test('folded with no standings to show, the status file problem stands beside the tag', async ($, on) => {
  world(on, { store: { [FOLDED_KEY]: true } })
  await start($)
  const band = await desktopBand($)
  expect(shownText(band)).toContain('no status file yet')
  expect(card(band)).toBeUndefined()
})

test('the terminal band draws no fold of its own and keeps its one line', async ($, on) => {
  const w = world(on, { store: { [FOLDED_KEY]: true } })
  w.setStatus(statusDoc())
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'terminal', component: 'AbovePrompt', props: BAND_PROPS })
  expect(await ui.find({ type: 'Button', key: 'fold' })).toBeUndefined()
  expect(shownText(await ui.drawn())).toMatch(withMoments(ALPHA_LINE))
  await ui.unmount()
})

/** status.json with alpha's 5-hour window as given. */
function withAlphaFiveHour(fiveHour: Record<string, unknown>) {
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[1]!.fiveHour = { ...accounts[1]!.fiveHour, ...fiveHour }
  return doc
}

async function panelText($: any): Promise<string> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  await ui.unmount()
  return text
}

test('the panel marks a 5-hour reset time ≈ only where it was inferred, whatever the figure', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlphaFiveHour({ estimated: true, anchorExact: true }))
  await start($)
  expect(await panelText($)).toMatch(/5-hour≈67%↻50mresets [A-Z][a-z]{2} \d\d:\d\d/)
  w.setStatus(withAlphaFiveHour({ estimated: true, anchorExact: false }), T0 + 1)
  await w.clock.advance(15_000)
  expect(await panelText($)).toMatch(/5-hour≈67%↻49mresets ≈[A-Z][a-z]{2} \d\d:\d\d/)
})

test('the panel marks how a weekly reset time was made only beside one, and in no words', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[0]!.weekly = { ...accounts[0]!.weekly, resetsAt: null, anchorExact: false }
  w.setStatus(doc)
  await start($)
  const text = await panelText($)
  expect(text).not.toContain('reset time')
  expect(text).toContain('Weekly≈96%● alpha')   // beta's week has no reset time: nothing beside it
  expect(text).toMatch(withMoments('Weekly69%↻<when>in 5d 0h'))   // alpha's, read: no ≈
})

test('a countdown with no figure before it is marked ≈ only where its reset time was inferred', async ($, on) => {
  const w = world(on)
  const running = { state: 'running', percent: null, resetsAt: iso(T0 + 50 * MINUTE), estimated: true }
  w.setStatus(withAlphaFiveHour({ ...running, anchorExact: false }))
  await start($)
  expect(shownText(await desktopBand($))).toContain('5hrunning↻≈50m')
  w.setStatus(withAlphaFiveHour({ ...running, anchorExact: true }), T0 + 1)
  await w.clock.advance(15_000)
  expect(shownText(await desktopBand($))).toContain('5hrunning↻49m')
})
