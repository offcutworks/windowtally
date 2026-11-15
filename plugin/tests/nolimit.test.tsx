/**
 * An account with no 5-hour limit: status.json's 5-hour state `no_limit` (the contract stated in
 * windowtally/status_file.py). The desktop's in-use line and the panel lead with its weekly window, at the scale the
 * 5-hour window otherwise takes, with no meter for the 5-hour window; the panel says it has no 5-hour limit, the band
 * shows no 5-hour window at all. Which windows each band surface draws is `bandwindows.test.tsx`'s; this file holds the
 * weekly window's scale. Read as each surface receives the tree; what the desktop app paints is checked by eye.
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BAND_PROPS, HOUR, PANE, PANE_PROPS, PLUGIN, T0, iso, keyedBox, shownText, start, statusDoc, withMoments,
  world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown }

const NO_LIMIT = {
  state: 'no_limit', percent: null, resetsAt: null, asOf: iso(T0 - 2 * HOUR), estimated: false, exhaustsAt: null,
  anchorExact: false,
}

function children(node: Node | undefined): Node[] {
  const list = Array.isArray(node?.children) ? (node!.children as unknown[]).flat(Infinity) : [node?.children]
  return list.filter((child): child is Node => typeof child === 'object' && child !== null)
}

function walk(node: Node): Node[] {
  return [node, ...children(node).flatMap(walk)]
}

/** The innermost Text whose words are `shown`, a `<when>` in it standing for a weekly reset's weekday and time (`withMoments`). */
function text(node: Node, shown: string): Node | undefined {
  const pattern = withMoments(shown, 'whole')
  return walk(node).filter(n => n.type === 'Text' && pattern.test(shownText(n))).pop()
}

/** The world's document with the given accounts' 5-hour windows removed. */
function withoutLimit(...uuids: string[]): Record<string, unknown> {
  const doc = statusDoc()
  for (const account of doc.accounts as Array<Record<string, any>>) {
    if (uuids.includes(account.uuid)) account.fiveHour = { ...NO_LIMIT }
  }
  return doc
}

async function band($: any, surface: string): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

async function panel($: any): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

test('on the desktop the account in use leads with its week at the 5-hour scale, with one meter', async ($, on) => {
  const w = world(on)
  w.setStatus(withoutLimit(ALPHA))
  await start($)
  const tree = await band($, 'desktop')
  const inUse = keyedBox(tree, 'in-use')!
  expect(shownText(inUse)).toMatch(withMoments('● alpha (app, CLI, next)week69%↻<when>', 'whole'))
  expect(text(inUse, '69%')?.props).toMatchObject({ size: 'heading', weight: 'bold' })
  expect(text(inUse, '↻<when>')?.props).toMatchObject({ weight: 'semibold' })
  expect(text(tree, 'no limit')).toBeUndefined()
  const meters = walk(tree).filter(node => node.type === 'Svg')
  expect(meters.map(m => [m.props?.alt, m.props?.width])).toEqual([['weekly window 69% used', 72]])
})

test('the panel leads with the weekly row at the 5-hour scale, the 5-hour row saying there is no limit', async ($, on) => {
  const w = world(on)
  w.setStatus(withoutLimit(ALPHA))
  await start($)
  const alpha = walk(await panel($)).find(node => node.type === 'Box' && node.props?.key === `account-${ALPHA}`)!
  const [, content] = children(alpha)
  const rows = children(content).slice(1).map(shownText)
  expect(rows[0]).toMatch(/^Weekly69%/)
  expect(rows[1]).toMatch(/^5-hourno limit/)
  expect(text(alpha, '69%')?.props).toMatchObject({ size: 'heading', weight: 'bold' })
  expect(walk(alpha).filter(node => node.type === 'Svg').map(m => m.props?.alt)).toEqual(['weekly window 69% used'])
})
