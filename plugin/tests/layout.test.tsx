/**
 * The desktop band's use of space, from version 3 of status.json (the contract stated in
 * windowtally/status_file.py): unfolded, the fold button over Details in a column beside the account lines, the fault
 * flags after the account in use and the other accounts in the compact words; folded, the fault flags right after the
 * fold button, with no Details; and the terminal's full words. What the desktop app paints from these trees is checked
 * by eye; here the trees are read as each surface receives them.
 */

import { expect, test } from 'claude-code/testing'
import {
  BAND_PROPS, HOUR, MINUTE, PLUGIN, T0, expectLines, iso, shownText, start, statusDoc, withMoments, world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown[] }

/** beta in the compact words; `<when>` is a weekly reset's weekday and time (`withMoments`). */
const BETA_COMPACT = 'beta 5h – week ≈96% ↻<when>'
/** The fault flags as the folded band's units show them, each after the first opening with the band's separator. */
const FLAGS = ['all accounts at their limit · first opens ↻2h 00m', '│ status 10m old', '│ 1 source problem']
/** The same flags as groups of the in-use line, which stand apart by layout. */
const FLAG_GROUPS = FLAGS.map(flag => flag.replace(/^│ /, ''))

/** The world's document with every fault the band flags. */
function faulted(): Record<string, unknown> {
  return statusDoc({
    generatedAt: iso(T0 - 10 * MINUTE),
    sourceErrors: ['transcripts: disk unreadable'],
    recommended: {
      account: null, reason: 'Every account is at its limit.', reliefAt: iso(T0 + 2 * HOUR), reliefExact: true,
    },
  })
}

function children(node: Node): Node[] {
  return (node.children ?? []).flatMap(child => typeof child === 'object' && child !== null ? [child as Node] : [])
}

function walk(node: Node): Node[] {
  return [node, ...children(node).flatMap(walk)]
}

async function drawn($: any, surface: string): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

/** The desktop band's two parts: what stands first, and what stands beside it. */
function parts(band: Node): { area: Node; beside: Node[] } {
  const [area, ...beside] = children(band)
  return { area: area!, beside }
}

function keyed(tree: Node, key: string): Node | undefined {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === key)
}

test('on the desktop Details stands under the fold button, beside the column the account lines wrap in', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const band = await drawn($, 'desktop')
  expect(band.type).toBe('Box')
  expect(band.props?.flexDirection).toBe('row')
  expect(band.props?.flexWrap ?? 'nowrap').toBe('nowrap')
  expect(band.props?.alignItems).toBe('flex-start')
  const { area: controls, beside } = parts(band)
  expect(controls.props?.key).toBe('controls')
  expect(controls.props?.flexDirection).toBe('column')
  expect(controls.props?.flexShrink).toBe(0)
  expect(children(controls).map(holder => shownText(holder))).toEqual(['[Accounts ▾]', '[Details]'])
  expect(beside.length).toBe(1)
  const accounts = beside[0]!
  expect(accounts.props?.key).toBe('accounts')
  expect(accounts.props?.flexGrow).toBe(1)
  expect(shownText(accounts)).not.toContain('[Details]')
  for (const line of children(accounts)) expect(walk(line).some(node => node.props?.flexWrap === 'wrap')).toBe(true)
  // The desktop app reshapes a row whose last children are buttons; no row holds a Button of its own.
  for (const row of [band, accounts]) expect(children(row).some(child => child.type === 'Button')).toBe(false)
})

test('on the desktop the fault flags stand after the account in use, then the other accounts in the compact words', async ($, on) => {
  const w = world(on)
  w.setStatus(faulted())
  await start($)
  const band = await drawn($, 'desktop')
  const groups = children(keyed(band, 'in-use')!)
  // With every account at its limit none is recommended, so alpha carries no `next`.
  expectLines(groups.map(group => shownText(group)), ['● alpha (app, CLI)', '5h≈67%↻50m', 'week69%↻<when>', ...FLAG_GROUPS])
  expectLines(children(keyed(band, 'others-units')!).map(unit => shownText(unit)), [BETA_COMPACT])
  for (const group of groups) expect(group.props?.flexShrink).toBe(1)
})

test('the desktop marks a window not started with a dim dash, and the terminal keeps the full words', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const desktop = await drawn($, 'desktop')
  const dash = walk(desktop).find(node => node.type === 'Text' && shownText(node) === '–')
  expect(dash?.props?.dimColor).toBe(true)
  expect(shownText(desktop)).not.toContain('not started')
  const terminal = await drawn($, 'terminal')
  const text = shownText(terminal)
  expect(text).toMatch(withMoments(
    'alpha (app, CLI, next)  5h ≈67% ↻50m  week 69% ↻<when>  │  beta  5h not started  week ≈96% ↻<when>'))
  expect(text).toContain('[Details]')
  expect(walk(terminal).some(node => node.type === 'Button' && node.props?.key === 'fold')).toBe(false)
})

test('a weekly window not started takes the same dash on the desktop', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[1]!.weekly = { ...accounts[1]!.weekly, state: 'not_started', percent: 0, resetsAt: null }
  w.setStatus(doc)
  await start($)
  const weekly = children(keyed(await drawn($, 'desktop'), 'in-use')!)[2]!
  expect(shownText(weekly)).toBe('week–')
  expect(walk(weekly).find(node => node.type === 'Text' && shownText(node) === '–')?.props?.dimColor).toBe(true)
  const meter = walk(weekly).find(node => node.type === 'Svg')
  expect(meter?.props?.alt).toBe('weekly window not started')
  expect(meter?.props?.source.match(/<rect/g)).toHaveLength(1)   // the track alone, an empty meter
})

test('folded, the tag, the other accounts and the flags share the line with no Details, and the card speaks the compact words',
  async ($, on) => {
  const w = world(on, { store: { bandFolded: true } })
  w.setStatus(faulted())
  await start($)
  const band = await drawn($, 'desktop')
  const { area, beside } = parts(band)
  expect(beside).toEqual([])
  expect(shownText(band)).not.toContain('[Details]')
  const units = children(area)
  expect(units[0]!.props?.key).toBe('fold-tag')
  expectLines(units.slice(1).map(unit => shownText(unit)), [`● ${BETA_COMPACT}`, `│ ${FLAGS[0]}`, ...FLAGS.slice(1)])
  const card = walk(units[0]!).find(node => node.type === 'Box' && node.props?.position === 'absolute')
  const text = shownText(card)
  expect(text).toMatch(withMoments('5h ≈67% ↻50m week 69% ↻<when>'))
  expect(text).toMatch(withMoments('5h – week ≈96% ↻<when>'))
})

test('with no standings to show, the problem stands in the account column and Details beside it', async ($, on) => {
  world(on)
  await start($)
  const { area: controls, beside } = parts(await drawn($, 'desktop'))
  expect(beside.map(node => node.props?.key)).toEqual(['accounts'])
  expect(shownText(beside[0])).toContain('no status file yet')
  expect(children(controls).map(holder => shownText(holder))).toEqual(['[Accounts ▾]', '[Details]'])
})
