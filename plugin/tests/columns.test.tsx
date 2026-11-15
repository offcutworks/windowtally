/**
 * The band's two columns on the desktop and its one line on the terminal, the session's own account set apart on
 * both, from version 3 of status.json (the contract stated in windowtally/status_file.py). What the desktop
 * app paints from these trees is checked by eye; here the trees are read as each surface receives them.
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BAND_PROPS, BETA, HOUR, MINUTE, PANE, PANE_PROPS, PLUGIN, T0, expectLines, iso, shownText, start, statusDoc,
  withMoments, world,
} from './world'

type Node = { type?: string; props?: Record<string, any>; children?: unknown }

const GAMMA = 'cccccccc-0000-4000-8000-000000000003'
const LONG_NAME = 'harbourlight.tangerine.longname'

function children(node: Node | undefined): Node[] {
  const list = Array.isArray(node?.children) ? (node!.children as unknown[]).flat(Infinity) : [node?.children]
  return list.filter((child): child is Node => typeof child === 'object' && child !== null)
}

function walk(node: Node): Node[] {
  return [node, ...children(node).flatMap(walk)]
}

function keyed(tree: Node, key: string): Node | undefined {
  return walk(tree).find(node => node.type === 'Box' && node.props?.key === key)
}

async function drawn($: any, surface: string): Promise<Node> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
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

/** A third account, gamma, idle and well inside its limits. */
function gamma(): Record<string, unknown> {
  return {
    uuid: GAMMA, email: 'gamma@example.com', label: 'gamma', isDesktop: false, isCli: false,
    lastActivity: iso(T0 - 50 * HOUR),
    fiveHour: { state: 'not_started', percent: 0, resetsAt: null, asOf: iso(T0 - 50 * HOUR), estimated: false,
                exhaustsAt: null },
    weekly: { state: 'current', percent: 12, resetsAt: iso(T0 + 2 * 24 * HOUR), asOf: iso(T0 - 50 * HOUR),
              estimated: false, exhaustsAt: null, anchorExact: true },
    subscription: null,
  }
}

test('unfolded, the desktop band is two columns: the fold button over Details, beside the account lines', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const band = await drawn($, 'desktop')
  expect(band.props?.flexDirection).toBe('row')
  const [controls, accounts, ...rest] = children(band)
  expect(rest).toEqual([])
  expect(controls?.props?.key).toBe('controls')
  expect(controls?.props?.flexDirection).toBe('column')
  expect(controls?.props?.flexShrink).toBe(0)
  expect(children(controls).map(holder => holder.props?.key)).toEqual(['fold-tag', 'details-holder'])
  expect(children(controls).map(holder => shownText(holder))).toEqual(['[Accounts ▾]', '[Details]'])
  expect(accounts?.props?.key).toBe('accounts')
  expect(accounts?.props?.flexDirection).toBe('column')
  expect(accounts?.props?.flexGrow).toBe(1)
  const buttons = walk(band).filter(node => node.type === 'Button')
  const fold = buttons.find(button => button.props?.key === 'fold')
  const details = buttons.find(button => button.props?.key === 'details')
  expect([fold?.props?.plain, fold?.props?.dimColor]).toEqual([true, true])
  expect([details?.props?.plain, details?.props?.dimColor ?? false]).toEqual([true, false])
  // A Button draws its own label alone, and the desktop app reshapes a row whose last children are buttons.
  expect(buttons.every(button => children(button).length === 0)).toBe(true)
  for (const node of walk(band).filter(n => n.type === 'Box' && n.props?.key !== 'fold-tag' && n.props?.key !== 'details-holder')) {
    expect(children(node).some(child => child.type === 'Button')).toBe(false)
  }
})

test('the account in use stands on a line of its own, its 5-hour figure largest, with meters and countdowns', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const band = await drawn($, 'desktop')
  const line = keyed(band, 'in-use')!
  expect(line.props?.flexWrap).toBe('wrap')
  const groups = children(line)
  expectLines(groups.map(group => shownText(group)), ['● alpha (app, CLI, next)', '5h≈67%↻50m', 'week69%↻<when>'])
  expect(groups.every(group => group.props?.flexWrap === 'wrap' && group.props?.flexShrink === 1)).toBe(true)
  const texts = walk(line).filter(node => node.type === 'Text')
  const text = (shown: string) => {
    const pattern = withMoments(shown, 'whole')
    return texts.find(node => pattern.test(shownText(node)))
  }
  expect(text('● ')?.props?.color).toBe('claude')
  expect(text('alpha')?.props?.weight).toBe('semibold')
  expect(text(' (app, CLI, next)')?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  expect(text('≈67%')?.props).toMatchObject({ size: 'heading', weight: 'bold', tabular: true })
  expect(text('↻50m')?.props).toMatchObject({ weight: 'semibold', tabular: true })
  expect(text('69%')?.props).toMatchObject({ size: 'footnote', weight: 'semibold', tabular: true })
  expect(text('↻<when>')?.props).toMatchObject({ size: 'footnote', dimColor: true, tabular: true })
  const meters = walk(line).filter(node => node.type === 'Svg')
  expect(meters.map(m => [m.props?.width, m.props?.height])).toEqual([[72, 8], [44, 5]])
  expect(meters.map(m => m.props?.alt)).toEqual(['5-hour window ≈67% used', 'weekly window 69% used'])
  expect(meters[0]!.props?.source).toContain('width="48"')   // 67 % of 72 pixels, rounded
  expect(walk(band).some(node => node.props?.color === 'transparent')).toBe(false)
})

test('the other accounts follow under a grey dot, compact, smaller and dim, each unit able to wrap', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  ;(doc.accounts as unknown[]).push(gamma())
  w.setStatus(doc)
  await start($)
  const band = await drawn($, 'desktop')
  const others = keyed(band, 'others')!
  const [dot, units] = children(others)
  expect(shownText(dot)).toBe('● ')
  const dotText = walk(dot!).find(node => node.type === 'Text')
  expect(dotText?.props?.dimColor).toBe(true)
  expect(dotText?.props?.size).toBeUndefined()   // the in-use dot's size, so the first name stands under its name
  expect(units?.props?.key).toBe('others-units')
  expect(units?.props?.flexWrap).toBe('wrap')
  expectLines(children(units).map(unit => shownText(unit)), ['beta 5h – week ≈96% ↻<when>', '│ gamma 5h – week 12% ↻<when>'])
  for (const unit of children(units)) {
    expect(unit.props?.flexShrink).toBe(1)
    expect(children(unit)[0]?.props).toMatchObject({ dimColor: true, size: 'footnote' })
  }
  expect(children(keyed(band, 'accounts')).map(line => line.props?.key)).toEqual(['in-use', 'others'])
})

test('the account set apart is the session\'s own: the app\'s in a session the app hosts, the CLI\'s otherwise', async ($, on) => {
  const doc = withAccounts({ [ALPHA]: { isCli: false }, [BETA]: { isCli: true } }, { cliAccount: BETA })
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(doc)
  await start($, 'terminal')
  const terminal = await drawn($, 'terminal')
  expect(shownText(terminal)).toMatch(withMoments('beta (CLI)  5h not started  week ≈96% ↻<when>  │  alpha (app, next)', 'start'))
  const name = walk(terminal).find(node => node.type === 'Text' && shownText(node) === 'beta')
  expect(name?.props).toMatchObject({ weight: 'semibold', color: 'claude' })
  const dim = walk(terminal).find(node => node.type === 'Text' && node.props?.dimColor && shownText(node).startsWith('alpha'))
  expect(dim).toBeDefined()
  expect(walk(dim!).some(node => node.props?.weight !== undefined)).toBe(false)
  // A figure past its threshold keeps its warning colours whichever account it is.
  expect(walk(terminal).find(node => node.type === 'Text' && shownText(node) === '≈96%')?.props?.color).toBe('error')
})

test('in a session the desktop app hosts, the app\'s account is the one set apart', async ($, on) => {
  const doc = withAccounts({ [ALPHA]: { isCli: false }, [BETA]: { isCli: true } }, { cliAccount: BETA })
  const w = world(on, { surfaces: ['desktop'] })
  w.setStatus(doc)
  await start($)
  const band = await drawn($, 'desktop')
  expect(shownText(children(keyed(band, 'in-use'))[0])).toBe('● alpha (app, next)')
  expect(shownText(keyed(band, 'others-units'))).toMatch(withMoments('beta (CLI) 5h – week ≈96% ↻<when>', 'whole'))
})

test('with the app at its sign-in page the others\' line stands alone in a desktop session', async ($, on) => {
  const w = world(on)
  w.setStatus(withAccounts({ [ALPHA]: { isDesktop: false } }, { desktopAccount: null, desktopSignedIn: false }))
  await start($)
  const band = await drawn($, 'desktop')
  expect(keyed(band, 'in-use')).toBeUndefined()
  expect(children(keyed(band, 'accounts')).map(line => line.props?.key)).toEqual(['others'])
  expectLines(children(keyed(band, 'others-units')).map(unit => shownText(unit)),
              ['alpha (CLI, next) 5h ≈67% ↻50m week 69% ↻<when>', '│ beta 5h – week ≈96% ↻<when>'])
})

/** The world's document with every fault the band flags. */
function faulted(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return statusDoc({
    generatedAt: iso(T0 - 10 * MINUTE),
    sourceErrors: ['transcripts: disk unreadable'],
    recommended: {
      account: null, reason: 'Every account is at its limit.', reliefAt: iso(T0 + 2 * HOUR), reliefExact: true,
    },
    ...overrides,
  })
}

const FLAGS = ['all accounts at their limit · first opens ↻2h 00m', 'status 10m old', '1 source problem']

test('the fault flags follow the weekly window on the in-use line, each a group that wraps as a whole', async ($, on) => {
  const w = world(on)
  w.setStatus(faulted())
  await start($)
  const groups = children(keyed(await drawn($, 'desktop'), 'in-use'))
  expectLines(groups.map(group => shownText(group)), ['● alpha (app, CLI)', '5h≈67%↻50m', 'week69%↻<when>', ...FLAGS])
  expect(groups.slice(3).every(group => group.props?.flexWrap === 'wrap' && group.props?.flexShrink === 1)).toBe(true)
})

test('with no account in use the flags take the in-use line\'s place, over the others', async ($, on) => {
  const w = world(on)
  w.setStatus(faulted({ desktopAccount: null, desktopSignedIn: false, cliAccount: null }))
  await start($)
  const band = await drawn($, 'desktop')
  const lines = children(keyed(band, 'accounts'))
  expect(lines.map(line => line.props?.key)).toEqual(['flags', 'others'])
  expect(children(lines[0]).map(group => shownText(group))).toEqual(FLAGS)
})

test('names longer than 16 characters are cut on every band, never in the panel', async ($, on) => {
  const w = world(on)
  w.setStatus(withAccounts({ [ALPHA]: { label: LONG_NAME }, [BETA]: { label: 'exactly16chars..' } }))
  await start($)
  for (const surface of ['desktop', 'terminal']) {
    const text = shownText(await drawn($, surface))
    expect(text).toContain('harbourlight.tan…')
    expect(text).not.toContain('longname')
    expect(text).toContain('exactly16chars..')
    expect(text).not.toContain('exactly16chars..…')
  }
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  expect(shownText(await ui.drawn())).toContain(LONG_NAME)
  await ui.unmount()
})

test('a name is cut on whole characters: an accent stays with its letter', async ($, on) => {
  const accented = 'é'.repeat(17)   // seventeen characters, each a letter and a combining accent
  const w = world(on)
  w.setStatus(withAccounts({ [ALPHA]: { label: accented } }))
  await start($)
  expect(shownText(await drawn($, 'desktop'))).toContain(`${'é'.repeat(16)}…`)
})

test('a meter is filled in its window\'s warning colours, and empty for a window not started', async ($, on) => {
  const w = world(on)
  w.setStatus(withAccounts(
    { [ALPHA]: { isDesktop: false, isCli: false }, [BETA]: { isDesktop: true, isCli: true } },
    { desktopAccount: BETA, cliAccount: BETA }))
  await start($)
  const line = keyed(await drawn($, 'desktop'), 'in-use')!
  const [fiveHour, weekly] = walk(line).filter(node => node.type === 'Svg')
  expect(fiveHour!.props?.alt).toBe('5-hour window not started')
  expect(fiveHour!.props?.source.match(/<rect/g)).toHaveLength(1)   // the track alone
  expect(weekly!.props?.source).toContain('fill="#d03b3b"')           // ≈96 % weekly: past its second threshold
  expect(walk(line).find(node => node.type === 'Text' && shownText(node) === '–')?.props?.dimColor).toBe(true)
  expect(walk(line).find(node => node.type === 'Text' && shownText(node) === '≈96%')?.props?.color).toBe('error')
})

test('a window with no figure shows its state\'s word and a marked countdown, and no meter', async ($, on) => {
  const w = world(on)
  w.setStatus(withAccounts({
    [ALPHA]: { fiveHour: { state: 'running', percent: null, resetsAt: iso(T0 + 50 * MINUTE), asOf: null,
                           estimated: true, exhaustsAt: null, anchorExact: false } },
  }))
  await start($)
  const line = keyed(await drawn($, 'desktop'), 'in-use')!
  expect(shownText(children(line)[1])).toBe('5hrunning↻≈50m')
  expect(walk(line).filter(node => node.type === 'Svg')).toHaveLength(1)
})

test('folded, the band is the fold button, the other accounts, the flags and a card of every account, names cut',
  async ($, on) => {
  const w = world(on, { store: { bandFolded: true } })
  w.setStatus(faulted({ accounts: withAccounts({ [ALPHA]: { label: LONG_NAME } }).accounts }))
  await start($)
  const band = await drawn($, 'desktop')
  expect(shownText(band)).not.toContain('[Details]')
  const units = children(keyed(band, 'units'))
  expect(shownText(units[0])).toContain('[Accounts ▸]')
  expectLines(units.slice(1).map(unit => shownText(unit)),
              ['● beta 5h – week ≈96% ↻<when>', `│ ${FLAGS[0]}`, `│ ${FLAGS[1]}`, `│ ${FLAGS[2]}`])
  const card = walk(units[0]!).find(node => node.type === 'Box' && node.props?.position === 'absolute')
  expect(shownText(card)).toContain('harbourlight.tan…')
  expect(shownText(card)).toMatch(withMoments('5h – week ≈96% ↻<when>'))
})

test('with no standings to show, the problem stands in the right column, the controls beside it', async ($, on) => {
  world(on)
  await start($)
  const band = await drawn($, 'desktop')
  expect(shownText(keyed(band, 'accounts'))).toContain('no status file yet')
  expect(children(keyed(band, 'controls')).map(holder => shownText(holder))).toEqual(['[Accounts ▾]', '[Details]'])
})
