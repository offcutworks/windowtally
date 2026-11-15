/**
 * The panel in the band's look (the maintainer's decision of 2026-10-27, recorded in PROJECT.md): every
 * account a block opened by the band's dot, its windows at the scale of the band's in-use line, the words whole, what
 * the band says said once. Read from version 3 of status.json (the contract stated in
 * windowtally/status_file.py) as each surface receives the tree; what the desktop app paints is checked by eye.
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BETA, HOUR, MINUTE, MOMENT, PANE, PANE_PROPS, PLUGIN, T0, iso, shownText, start, statusDoc, subscriptionOf,
  withMoments, world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown }

const DELTA = 'dddddddd-0000-4000-8000-000000000004'
const MARKS = '≈ inferred, not read · ↻ reset'

function children(node: Node | undefined): Node[] {
  const list = Array.isArray(node?.children) ? (node!.children as unknown[]).flat(Infinity) : [node?.children]
  return list.filter((child): child is Node => typeof child === 'object' && child !== null)
}

function walk(node: Node): Node[] {
  return [node, ...children(node).flatMap(walk)]
}

function texts(node: Node): Node[] {
  return walk(node).filter(n => n.type === 'Text')
}

/**
 * The innermost Text whose words are `shown`, a `<when>` in it standing for a weekly reset's weekday and time
 * (`withMoments`): a Text that only wraps it says the same.
 */
function text(node: Node, shown: string): Node | undefined {
  const pattern = withMoments(shown, 'whole')
  return texts(node).filter(n => pattern.test(shownText(n))).pop()
}

function block(tree: Node, uuid: string): Node {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === `account-${uuid}`)!
}

/** A block's rows under its first line: each a row of a name and the groups beside it. */
function rows(account: Node): Node[] {
  const [, content] = children(account)
  return children(content).slice(1)
}

async function panel($: any, surface = 'desktop'): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const tree = (await ui.drawn()) as Node
  await ui.unmount()
  return tree
}

/** The world's document, with the accounts' entries changed as given, by UUID. */
function withAccounts(changes: Record<string, Record<string, unknown>>, overrides: Record<string, unknown> = {}) {
  const doc = statusDoc(overrides)
  const accounts = doc.accounts as Array<Record<string, any>>
  for (const account of accounts) Object.assign(account, changes[account.uuid] ?? {})
  return doc
}

test('each account is a block opened by the band\'s dot, orange for the account in use, grey for the others', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const tree = await panel($)
  const alpha = block(tree, ALPHA)
  const beta = block(tree, BETA)
  expect(text(children(alpha)[0]!, '● ')?.props?.color).toBe('claude')
  expect(text(children(beta)[0]!, '● ')?.props?.dimColor).toBe(true)
  expect(text(alpha, 'alpha')?.props?.weight).toBe('semibold')
  expect(text(beta, 'beta')?.props?.weight).toBe('semibold')
  expect(text(beta, 'beta')?.props?.dimColor).toBeUndefined()
  expect(text(alpha, ' (desktop app, CLI, use next)')?.props).toMatchObject({ dimColor: true, size: 'footnote' })
})

test('on the terminal the account in use is set apart by weight and colour alone, and no meter is drawn', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(statusDoc({ cliAccount: BETA }))
  await start($, 'terminal')
  const tree = await panel($, 'terminal')
  expect(walk(tree).some(node => node.type === 'Svg')).toBe(false)
  const beta = block(tree, BETA)
  expect(text(beta, 'beta')?.props).toMatchObject({ weight: 'semibold', color: 'claude' })
  expect(text(children(beta)[0]!, '● ')?.props?.color).toBe('claude')
  const alpha = block(tree, ALPHA)
  expect(texts(alpha).some(node => shownText(node) === 'alpha' && node.props?.weight)).toBe(false)
  expect(texts(alpha).some(node => ['bold', 'semibold'].includes(node.props?.weight) && /%$/.test(shownText(node))))
    .toBe(false)
  // One size: what still tells the weekly window from the 5-hour one is its dim countdown.
  expect(text(alpha, '↻50m')?.props?.dimColor).toBeUndefined()
  expect(text(alpha, '↻<when>')?.props?.dimColor).toBe(true)
})

test('the windows stand at the scale of the band\'s in-use line, with its meters, in every block', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const tree = await panel($)
  const alpha = block(tree, ALPHA)
  expect(text(alpha, '≈67%')?.props).toMatchObject({ size: 'heading', weight: 'bold', tabular: true })
  expect(text(alpha, '↻50m')?.props).toMatchObject({ weight: 'semibold', tabular: true })
  expect(text(alpha, '69%')?.props).toMatchObject({ size: 'footnote', weight: 'semibold', tabular: true })
  expect(text(alpha, '↻<when>')?.props).toMatchObject({ size: 'footnote', dimColor: true, tabular: true })
  const meters = walk(alpha).filter(node => node.type === 'Svg')
  expect(meters.map(m => [m.props?.width, m.props?.height])).toEqual([[72, 8], [44, 5]])
  const beta = block(tree, BETA)
  expect(text(beta, '≈96%')?.props).toMatchObject({ size: 'footnote', weight: 'semibold' })
  expect(walk(beta).filter(node => node.type === 'Svg').map(m => m.props?.alt))
    .toEqual(['5-hour window not started', 'weekly window ≈96% used'])
})

test('the words stay whole: every window is named, in one width, and one not started or with no figure says so',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withAccounts({
      [ALPHA]: {
        fiveHour: { state: 'running', percent: null, resetsAt: iso(T0 + 50 * MINUTE), asOf: iso(T0 - 2 * HOUR),
                    estimated: true, exhaustsAt: null },
        weekly: { state: 'unknown', percent: null, resetsAt: null, asOf: null, estimated: false, exhaustsAt: null },
      },
    }))
    await start($)
    const tree = await panel($)
    const names = (uuid: string) => rows(block(tree, uuid)).map(row => children(row)[0]!)
    for (const uuid of [ALPHA, BETA]) {
      for (const name of names(uuid)) {
        const label = texts(name)[0]!
        expect(label.props).toMatchObject({ mono: true, dimColor: true })
        expect(shownText(label)).toHaveLength(6)
        expect(name.props?.flexShrink).toBe(0)
      }
    }
    expect(names(ALPHA).map(name => shownText(name))).toEqual(['5-hour', 'Weekly', 'Plan\u00a0\u00a0'])
    const shown = shownText(tree)
    expect(shown).toContain('5-hournot started')
    expect(shown).toContain('5-hourrunning')
    expect(shown).toContain('Weeklyunknown')
    expect(shown).not.toContain('the next message opens a window')
  })

test('beside a 5-hour countdown stand its reset time, ≈ where inferred, and the pace; beside a weekly reset, the time left',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withAccounts({
      [ALPHA]: {
        fiveHour: { state: 'running', percent: 67, resetsAt: iso(T0 + 50 * MINUTE), asOf: iso(T0 - 2 * HOUR),
                    estimated: false, exhaustsAt: iso(T0 + 30 * MINUTE), anchorExact: true },
      },
    }))
    await start($)
    const tree = await panel($)
    const [fiveHour, weekly] = rows(block(tree, ALPHA)).map(row => shownText(row))
    expect(fiveHour).toMatch(new RegExp(`↻50mresets ${MOMENT} · full at this pace ≈${MOMENT}$`))
    expect(weekly).toMatch(new RegExp(`69%↻${MOMENT}in 5d 0h$`))
    const [, betaWeekly] = rows(block(tree, BETA)).map(row => shownText(row))
    expect(betaWeekly).toMatch(new RegExp(`≈96%↻${MOMENT}in 3d 4h$`))   // inferred: its figure's ≈ says so
    expect(shownText(tree)).not.toContain('reset time')
    expect(shownText(tree)).not.toContain('(in ')
    const facts = text(block(tree, ALPHA), (fiveHour.match(/resets .*$/) ?? [''])[0])
    expect(facts?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  })

test('a reading\'s age is said once per block where both windows rest on it, beside each window where they differ',
  async ($, on) => {
    const w = world(on)
    const doc = statusDoc()
    const alpha = (doc.accounts as Array<Record<string, any>>)[1]!
    alpha.fiveHour = { ...alpha.fiveHour, asOf: iso(T0 - 10 * MINUTE) }
    w.setStatus(doc)
    await start($)
    const tree = await panel($)
    const betaLine = shownText(children(children(block(tree, BETA))[1]!)[0]!)
    expect(betaLine).toBe('betalast response 1d 6h ago · read 1d 8h ago')   // a name its e-mail gives: no e-mail
    expect(rows(block(tree, BETA)).map(row => shownText(row)).join('')).not.toContain('read ')
    const alphaLine = shownText(children(children(block(tree, ALPHA))[1]!)[0]!)
    expect(alphaLine).toBe('alpha (desktop app, CLI, use next)last response 1m ago')
    const [fiveHour, weekly] = rows(block(tree, ALPHA)).map(row => shownText(row))
    expect(fiveHour).toMatch(/ · read 10m ago$/)
    expect(weekly).toMatch(/ · read 2h 00m ago$/)
  })

test('the plan line closes the block, smaller and dim, its warnings in the warning colour, and no tag repeats the renewal',
  async ($, on) => {
    const w = world(on)
    w.setStatus(withAccounts({ [ALPHA]: { subscription: subscriptionOf({ daysLeft: 2, renewSoon: true }) } },
                             { renewalReminderDays: 3 }))
    await start($)
    const tree = await panel($)
    const plan = rows(block(tree, ALPHA))[2]!
    expect(shownText(plan)).toBe('Plan\u00a0\u00a0Ultra · paid until Mon 2 Nov (2d left)')   // no cost this month
    // The line is dim and footnote-sized, and its warning is not dimmed: no dim Text holds it.
    const line = texts(children(plan)[1]!)[0]!
    expect(line.props?.size).toBe('footnote')
    expect(line.props?.dimColor).toBeUndefined()
    const runs = children(line)
    expect(runs.map(run => shownText(run))).toEqual(['Ultra · paid until Mon 2 Nov', ' (2d left)'])
    expect(runs.map(run => [run.props?.dimColor ?? false, run.props?.color ?? null]))
      .toEqual([[true, null], [false, 'warning']])
    expect(shownText(children(children(block(tree, ALPHA))[1]!)[0]!)).not.toContain('renew')
  })

test('the head says only what the blocks cannot; the foot holds the status time and the marks', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const shown = shownText(await panel($))
  expect(shown).not.toContain('Desktop app:')
  expect(shown).not.toContain('CLI: alpha')
  expect(shown).toMatch(/^\[Open WindowTally\] Next: alpha has room left/)
  expect(shown.endsWith(`(12d left)Updated just now.${MARKS}`)).toBe(true)   // no word where there is no problem
  expect(shown).not.toContain('source problem')
})

test('the head names the desktop app at its sign-in page, an account WindowTally does not list, and a stale status',
  async ($, on) => {
    const w = world(on)
    const signedOut = withAccounts({ [ALPHA]: { isDesktop: false } }, { desktopAccount: null, desktopSignedIn: false })
    w.setStatus(signedOut)
    await start($)
    expect(shownText(await panel($))).toContain('Desktop app: at its sign-in page.Next:')
    w.setStatus(withAccounts({ [ALPHA]: { isDesktop: false } }, { desktopAccount: DELTA }), w.clock.now() + 1)
    await w.clock.advance(15_000)
    expect(shownText(await panel($))).toContain('Desktop app: dddddddd…, an account WindowTally does not list.Next:')
    w.setStatus(statusDoc({ generatedAt: iso(T0 - 20 * MINUTE) }), w.clock.now() + 1)
    await w.clock.advance(15_000)
    expect(shownText(await panel($))).toContain('The service may not be running: the status is 20m old.')
  })

test('nothing runs past the pane: a further line starts under the line\'s own content', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const alpha = block(await panel($), ALPHA)
  const [dot, content] = children(alpha)
  expect(dot!.props?.flexShrink).toBe(0)
  expect(content!.props).toMatchObject({ flexGrow: 1, flexShrink: 1 })
  expect(children(content)[0]!.props?.flexWrap).toBe('wrap')
  for (const row of rows(alpha)) {
    const [name, groups] = children(row)
    expect(name!.props?.flexShrink).toBe(0)
    expect(groups!.props).toMatchObject({ flexWrap: 'wrap', flexShrink: 1 })
  }
})
