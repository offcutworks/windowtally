/**
 * The panel behind the band's Details button, in the band's look: every account a block, every figure spelt out and
 * every name whole, what the band says said once.
 *
 * Head: a button that brings up the WindowTally window (window.ts), with what the last press came to beside it; then only
 * what the blocks cannot say — that the service may not be running, the desktop app at its sign-in page, an account
 * the app or the CLI uses that WindowTally does not list, a desktop app the status reports not running, which WindowTally's
 * window starts and the plugin does not, the CLI's condition — and the recommendation, `Next:` and its reason, with
 * the time left until the first account opens or room returns. A session the app hosts never reads the app not running
 * (status.ts, seenBySession).
 *
 * Blocks, one for every account the band lists (band.tsx, listed), in the service's order: the band's dot, orange
 * for the account the session's use is booked to (status.ts, accountInUse), as the band marks it, grey for the others;
 * the account's name, semibold, and its tags in full words (`desktop app`, or `desktop app, not running`, `CLI`,
 * `use next`); after them, smaller and dim, its e-mail where the name is the user's own, the age of its last response,
 * and the age of the reading its figures rest on where both windows rest on the same one, or the 5-hour window has no
 * limit. Under them the two windows at the scale of the band's in-use line (band.tsx, windowFigure) — the 5-hour figure
 * the panel's largest text with the band's meter and a semibold countdown, the weekly one smaller with its dim reset
 * weekday and time — each named in one width so the figures of every block stand in one column; a window not started
 * says `not started`, one with no figure `running` or `unknown`. An account with no 5-hour limit leads with its weekly
 * window, at the scale the 5-hour window otherwise takes, and its 5-hour row after it says `no limit`, small and dim.
 * Under the weekly row, each per-model window the service gives the account (Fable's), by the model's name at the
 * weekly scale, with its allowance's share of the week and the age of the claude.ai reading it rests on.
 * Beside a window, smaller and dim: the 5-hour window's wall-clock reset time, ≈ where it was inferred, or the time
 * left until the weekly one resets; the time the pace runs out; the reading's age where the two windows' readings
 * differ; and, beside a weekly one, the week's use by product where claude.ai reported more than one product, as the
 * window's card says it. The plan line closes the block, smaller and dim, its warnings in the warning colour. The other
 * accounts are not dimmed as on the band: the panel is where every listed account's figures are read. An account whose
 * plan has ended and that neither client uses (band.tsx, windowsLeftOut) is the exception: its block is one dim line —
 * its name, when its plan ended and when its week resets — with no figures, which would read as room left.
 *
 * Foot: the source problems, where there are any, how many accounts the user hid and where they are shown again, how
 * long ago the status was written, and one line for the panel's marks.
 *
 * Nothing runs past the pane's width: a line's groups wrap as wholes, and a further line starts under the line's own
 * content — a block's under the name, a window's under its figure — never at the pane's left edge.
 *
 * Surfaces: the desktop app raises the pane on its one surface, `desktop`, the surface it raises the band on (its
 * bundle, 2.42304.0.0, 2026-10-27), so a Text's size and an Svg are drawn there as on the band, as on every surface
 * whose element table carries an Svg; the CLI raises it on the terminal, which draws one size and no Svg, where the
 * account in use is set apart by weight and colour alone, its name semibold in the theme's `claude` colour, no figure
 * or countdown takes a weight, the weekly countdown stays dim, and no meter is drawn. A pane's site reshapes no row, a
 * row ending in a button included (measured in the desktop app 2.42304.0.0's bundle, 2026-10-22).
 */

import type { RenderElement } from 'claude-code'
import type { StatusAccount, StatusDocument, StatusSubscription, StatusWindow, StatusSnapshot } from '../types'
import {
  DOT, FIVE_HOUR_SCALE, group, listed, problemText, resetMark, scopedOf, STALE_MS, tags, WEEKLY_SCALE, weekMoment,
  weeklyLeads, windowFigure, windowsLeftOut, type DesktopTable, type Scale, type Table, type TagWords,
} from './band'
import { ago, day, parseTime, percentText, PLAN_NAMES, span, when } from './text'

type Part = string | RenderElement

/** The panel's tags, in full words. */
const FULL_TAGS: TagWords = { desktop: 'desktop app', closed: 'desktop app, not running', cli: 'CLI', next: 'use next' }

/** The width every row's name is drawn in: `5-hour` and `Weekly` alike, `Plan` padded with no-break spaces. */
const NAME_WIDTH = 6

/**
 * The surfaces whose element table carries an Svg (Claude Code's `Elements`: the desktop's, the mobile app's and the
 * editor's); every other, the terminal first, draws one size and no meter.
 */
const DRAWING_SURFACES: ReadonlySet<string> = new Set(['desktop', 'mobile', 'vscode'])

/**
 * The terminal draws one size: its figures and countdowns take no weight of their own, so that weight and colour set
 * the account in use apart alone; the weekly countdown stays dim, the one mark left between the two windows.
 */
const PLAIN_FIVE_HOUR: Scale = { ...FIVE_HOUR_SCALE, figureWeight: 'regular', countdownWeight: 'regular' }
const PLAIN_WEEKLY: Scale = { ...WEEKLY_SCALE, figureWeight: 'regular' }

/** How the surface drawing the pane draws: its meters' table, or null for none, and the windows' scales. */
type Look = { meters: DesktopTable | null; fiveHour: Scale; weekly: Scale }

function lookOf(T: Table, surface: string): Look {
  return DRAWING_SURFACES.has(surface)
    ? { meters: T as DesktopTable, fiveHour: FIVE_HOUR_SCALE, weekly: WEEKLY_SCALE }
    : { meters: null, fiveHour: PLAIN_FIVE_HOUR, weekly: PLAIN_WEEKLY }
}

/** A row's name, in the monospaced face so that every name takes NAME_WIDTH; padding that no surface collapses. */
function rowName(T: Table, name: string): RenderElement {
  const { Box, Text } = T
  return (
    <Box flexShrink={0}>
      <Text dimColor size="footnote" mono>{name.padEnd(NAME_WIDTH, ' ')}</Text>
    </Box>
  )
}

/** A row: its name, then its groups, which wrap as wholes under the row's own content. */
function row(T: Table, name: string, groups: RenderElement[]): RenderElement {
  const { Box } = T
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      {rowName(T, name)}
      <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={1} flexGrow={1} flexShrink={1}>
        {groups}
      </Box>
    </Box>
  )
}

/** Smaller dim words beside a figure or a name. */
function aside(T: Table, words: string[]): RenderElement | null {
  const { Box, Text } = T
  if (!words.length) return null
  return <Box flexShrink={1}><Text dimColor size="footnote">{words.join(' · ')}</Text></Box>
}

function readingAge(window: StatusWindow, now: number): string {
  const asOf = parseTime(window.asOf)
  return asOf === null ? 'no reading yet' : `read ${ago(now - asOf)}`
}

/**
 * Whether the block says its reading's age once: the two windows rest on one observation, or the 5-hour window, having
 * no limit, shows no figure that rests on one (windowtally_gui/live_model.py, shared_reading).
 */
function sharesReading(account: StatusAccount): boolean {
  return account.fiveHour.state === 'no_limit' || account.fiveHour.asOf === account.weekly.asOf
}

/**
 * The week's use by product as the window's card words it (windowtally_gui/live_model.py, products_text): the shares
 * above zero in claude.ai's order, with the report's age — `by product 3h ago: Claude Code 89%, Chats 11%`; null where
 * fewer than two products have a share, the figure saying all of it.
 */
function productsText(window: StatusWindow, now: number): string | null {
  const asOf = parseTime(window.byProduct?.asOf ?? null)
  const used = (window.byProduct?.rows ?? []).filter(row => row.percent > 0)
  if (asOf === null || used.length < 2) return null
  return `by product ${ago(now - asOf)}: ${used.map(row => `${row.name} ${percentText(row.percent)}`).join(', ')}`
}

/**
 * The name the account would have without one of the user's own: its e-mail's local part, else the e-mail, else the
 * short UUID (windowtally/accounts.py, default_label).
 */
function defaultLabel(account: StatusAccount): string {
  const email = account.email
  if (email && email.includes('@')) return email.slice(0, email.indexOf('@'))
  return email || account.uuid.slice(0, 8)
}

/** The account's e-mail where its name is the user's own, so the e-mail says what the name does not; else null. */
function emailNote(account: StatusAccount): string | null {
  const email = account.email
  return email && email !== account.label && defaultLabel(account) !== account.label ? email : null
}

/**
 * What stands beside a window's reset: for the 5-hour window the wall-clock reset time, ≈ only where it was inferred
 * (`resetMark`), for the weekly one the time left until it resets, its weekday standing in the reset itself; when the
 * pace runs out; the reading's age where the block does not say it; and beside a weekly one the week's use by product.
 */
function windowFacts(kind: string, window: StatusWindow, now: number, sayReading: boolean): string[] {
  const facts: string[] = []
  const reset = parseTime(window.resetsAt)
  if (reset !== null) {
    facts.push(kind === 'five_hour' ? `resets ${resetMark(window)}${when(reset)}` : `in ${span(reset - now)}`)
  }
  const exhausts = parseTime(window.exhaustsAt)
  if (exhausts !== null) facts.push(`full at this pace ≈${when(exhausts)}`)
  if (sayReading) facts.push(readingAge(window, now))
  const products = kind === 'seven_day' ? productsText(window, now) : null
  if (products !== null) facts.push(products)
  return facts
}

function windowRow(T: Table, look: Look, name: string, title: string, kind: string, window: StatusWindow, now: number,
                   scale: Scale, sayReading: boolean, more: string[] = []): RenderElement {
  const figure = windowFigure(T, title, kind, window, now, scale, { meters: look.meters, notStarted: 'not started' })
  const facts = aside(T, [...windowFacts(kind, window, now, sayReading), ...more])
  return row(T, name, facts ? [group(T, figure), facts] : [group(T, figure)])
}

/**
 * A per-model window's row, under the weekly one at its scale: its figure, then its allowance's share of the week and
 * the age of the claude.ai reading it rests on, always, since it is read apart from the other windows; where it is
 * unknown, why.
 */
function scopedRows(T: Table, look: Look, account: StatusAccount, now: number): RenderElement[] {
  const given = account.weekly.scoped ?? []
  return scopedOf(account).map(({ name, kind, window }, index) => {
    const scoped = given[index]!
    const asOf = parseTime(scoped.asOf)
    const more = [
      scoped.allowanceOfWeekly === null ? null : `${percentText(scoped.allowanceOfWeekly)} of the weekly limit`,
      scoped.state === 'unknown' ? 'a reset came since claude.ai was read' : null,
      asOf === null ? null : `read on claude.ai ${ago(now - asOf)}`,
    ].filter((fact): fact is string => fact !== null)
    return windowRow(T, look, name, `${name} allowance`, kind, window, now, look.weekly, false, more)
  })
}

/** What the profile says beside the bills, when it says something else. */
function profileText(subscription: StatusSubscription): string | null {
  const named = PLAN_NAMES[subscription.profilePlan ?? ''] ?? 'no plan WindowTally compares'
  switch (subscription.profileCheck) {
    case 'differs':
      return `the profile names ${named}`
    case 'profile-older':
      return `the profile, fetched before this period began, names ${named}`
    case 'no-bill-today':
      return `the profile names ${named}, but no recorded bill covers today`
    default:
      return null
  }
}

/**
 * The account's plan by its bills: in effect today and paid up to when, and the profile's word where it says
 * otherwise. The line is dim and its warnings are not: a dim Text dims the Texts inside it on the terminal, so each run
 * is a sibling.
 */
function planRow(T: Table, subscription: StatusSubscription | null): RenderElement | null {
  if (subscription === null) return null
  const { Box, Text } = T
  const dim = (words: string) => <Text dimColor>{words}</Text>
  const warning = (words: string) => <Text color="warning">{words}</Text>
  const until = subscription.paidUntil === null ? '' : day(subscription.paidUntil)
  const parts: Part[] = []
  if (subscription.state === 'active') {
    parts.push(dim(`${subscription.planName ?? 'a recorded plan'} · paid until ${until}`))
    if (subscription.daysLeft !== null) {
      const left = ` (${subscription.daysLeft}d left)`
      parts.push(subscription.renewSoon ? warning(left) : dim(left))
    }
  } else if (subscription.state === 'ended') {
    parts.push(warning(`ended ${until}`))
  } else if (subscription.state === 'upcoming') {
    parts.push(dim(`first period starts ${until}`))
  } else if (subscription.state === 'unread') {
    // Its bills may not all have been read: no plan, end or absence is said, only where to look.
    parts.push(warning('bills not all read'), dim(' · see Source problems below'))
  } else {
    parts.push(dim('no bills recorded'))
  }
  const profile = profileText(subscription)
  if (profile !== null) parts.push(dim(` · ${profile}`))
  return row(T, 'Plan', [<Box flexShrink={1}><Text size="footnote">{parts}</Text></Box>])
}

/**
 * An account whose plan has ended and that neither client uses (band.tsx, windowsLeftOut): one dim line — its name,
 * when its plan ended, when its week resets, and its e-mail where the name is the user's own — and no figures.
 */
function endedBlock(T: Table, account: StatusAccount, now: number): RenderElement {
  const { Box, Text } = T
  const paidUntil = account.subscription?.paidUntil ?? null
  const reset = parseTime(account.weekly.resetsAt)
  const words = [
    paidUntil === null ? 'plan ended' : `plan ended ${day(paidUntil)}`,
    reset === null ? null : `week resets ${resetMark(account.weekly)}${weekMoment(reset, now)}`,
    emailNote(account),
  ].filter((word): word is string => word !== null)
  return (
    <Box key={`account-${account.uuid}`} flexDirection="row" alignItems="flex-start" marginTop={1}>
      <Box flexShrink={0}><Text dimColor>{DOT}</Text></Box>
      <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={1} flexGrow={1} flexShrink={1}>
        {group(T, [<Text dimColor>{account.label}</Text>])}
        {aside(T, words)}
      </Box>
    </Box>
  )
}

/**
 * An account's first line: the dot, then its name and tags, then, smaller and dim, its e-mail, its last response and,
 * where both windows share it, its reading's age. On the terminal the account in use is set apart by its name in the
 * `claude` colour; elsewhere the dot's colour does it, every name semibold.
 */
function headingGroups(T: Table, look: Look, status: StatusDocument, account: StatusAccount, isInUse: boolean,
                       now: number): RenderElement[] {
  const { Text } = T
  const accountTags = tags(account, status, FULL_TAGS)
  const name = look.meters ? <Text weight="semibold">{account.label}</Text>
    : isInUse ? <Text weight="semibold" color="claude">{account.label}</Text> : account.label
  const named: Part[] = [name]
  if (accountTags.length) named.push(<Text dimColor size="footnote">{` (${accountTags.join(', ')})`}</Text>)
  const activity = parseTime(account.lastActivity)
  const facts = [
    emailNote(account),
    activity === null ? null : `last response ${ago(now - activity)}`,
    sharesReading(account) ? readingAge(account.weekly, now) : null,
  ].filter((fact): fact is string => fact !== null)
  const groups = [group(T, [<Text>{named}</Text>])]
  const more = aside(T, facts)
  if (more) groups.push(more)
  return groups
}

function accountBlock(T: Table, look: Look, status: StatusDocument, account: StatusAccount, isInUse: boolean,
                      now: number): RenderElement {
  const { Box, Text } = T
  if (windowsLeftOut(account)) return endedBlock(T, account, now)
  const sayReading = !sharesReading(account)
  const leads = weeklyLeads(account)
  const fiveHour = windowRow(T, look, '5-hour', '5-hour window', 'five_hour', account.fiveHour, now,
                             leads ? look.weekly : look.fiveHour, sayReading)
  const weekly = windowRow(T, look, 'Weekly', 'weekly window', 'seven_day', account.weekly, now,
                           leads ? look.fiveHour : look.weekly, sayReading)
  const scoped = scopedRows(T, look, account, now)
  const rows = leads ? [weekly, ...scoped, fiveHour] : [fiveHour, weekly, ...scoped]
  const plan = planRow(T, account.subscription)
  if (plan) rows.push(plan)
  return (
    <Box key={`account-${account.uuid}`} flexDirection="row" alignItems="flex-start" marginTop={1}>
      <Box flexShrink={0}>{isInUse ? <Text color="claude">{DOT}</Text> : <Text dimColor>{DOT}</Text>}</Box>
      <Box flexDirection="column" rowGap="xs" flexGrow={1} flexShrink={1}>
        <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={1}>
          {headingGroups(T, look, status, account, isInUse, now)}
        </Box>
        {rows}
      </Box>
    </Box>
  )
}

/** What the panel's window button last came to: being carried out, or the sentence it ended with. */
export type WindowAsk = { isAsking: boolean; said: string | null }

/** The panel's head: the button that brings up the WindowTally window, and what the last press came to. */
function windowHead(T: Table, ask: WindowAsk, onWindow: () => void): RenderElement {
  const { Box, Text, Button } = T
  const said = ask.isAsking ? 'Bringing up the window…' : ask.said
  return (
    <Box flexDirection="row" gap={1} marginBottom={1}>
      <Button key="window" label="Open WindowTally" onPress={onWindow} />
      {said ? <Text dimColor>{said}</Text> : <Text> </Text>}
    </Box>
  )
}

/**
 * `inUse` is the account the session's use is booked to (status.ts, accountInUse), or null; `surface` the one drawing
 * the pane.
 */
export function panelTree(T: Table, surface: string, snapshot: StatusSnapshot | null, now: number,
                          inUse: StatusAccount | null, ask: WindowAsk, onWindow: () => void): RenderElement {
  const { Box } = T
  return (
    <Box flexDirection="column">
      {windowHead(T, ask, onWindow)}
      {standingsTree(T, lookOf(T, surface), snapshot, now, inUse)}
    </Box>
  )
}

/**
 * The accounts the desktop app and the CLI use where no block's tag names them: an app at its sign-in page, which is
 * no account's, and an account WindowTally does not list. An account not known is not said. Then an app the status
 * reports not running, which the plugin does not start: the WindowTally window does.
 */
function clientWords(status: StatusDocument): string[] {
  const unlisted = (uuid: string | null) =>
    uuid !== null && !status.accounts.some(account => account.uuid === uuid) ? uuid.slice(0, 8) : null
  const words: string[] = []
  if (status.desktopSignedIn === false) words.push('Desktop app: at its sign-in page.')
  else {
    const desktop = unlisted(status.desktopAccount)
    if (desktop) words.push(`Desktop app: ${desktop}…, an account WindowTally does not list.`)
  }
  if (status.desktopRunning === false) words.push('The desktop app is not running; start it from the WindowTally window.')
  const cli = unlisted(status.cliAccount)
  if (cli) words.push(`CLI: ${cli}…, an account WindowTally does not list.`)
  return words
}

/** The head's lines after the button: the faults the blocks cannot show, then the recommendation. */
function headLines(T: Table, status: StatusDocument, now: number): RenderElement[] {
  const { Text } = T
  const lines: RenderElement[] = []
  const generated = parseTime(status.generatedAt)
  if (generated !== null && now - generated > STALE_MS) {
    lines.push(<Text color="warning">{`The service may not be running: the status is ${span(now - generated)} old.`}</Text>)
  }
  const clients = clientWords(status)
  if (clients.length) lines.push(<Text>{clients.join(' ')}</Text>)
  if (status.cliCondition) {
    lines.push(<Text color="warning">{`The CLI does not follow the desktop app: ${status.cliCondition}`}</Text>)
  }
  // The reason names the moment room returns or the first account opens; the time left until it is added to it, ≈
  // where the moment was inferred, as the window's header adds it (windowtally_gui/live_model.py, next_text).
  const relief = parseTime(status.recommended.reliefAt)
  const reason = status.recommended.reason
  const approx = status.recommended.reliefExact ? '' : '≈'
  lines.push(
    <Text>
      {relief === null ? `Next: ${reason}`
        : `Next: ${reason.replace(/\.$/, '')} (in ${approx}${span(relief - now)}).`}
    </Text>,
  )
  return lines
}

/** How many accounts the user hid, said where the panel lists none of them; null while none is hidden. */
function hiddenWords(status: StatusDocument): string | null {
  const count = status.accounts.length - listed(status.accounts).length
  if (!count) return null
  const accounts = count === 1 ? '1 account hidden' : `${count} accounts hidden`
  return `${accounts}: Arrange accounts… in the WindowTally window shows ${count === 1 ? 'it' : 'them'}.`
}

/**
 * The foot: the source problems, where there are any, the accounts hidden, how long ago the status was written, and
 * what the panel's marks are.
 */
function foot(T: Table, status: StatusDocument, now: number): RenderElement {
  const { Box, Text } = T
  const generated = parseTime(status.generatedAt)
  const hidden = hiddenWords(status)
  return (
    <Box flexDirection="column" marginTop={1}>
      {status.sourceErrors.length
        ? [<Text color="warning">Source problems:</Text>,
           ...status.sourceErrors.map(problem => <Text>{`  ${problem}`}</Text>)]
        : []}
      {hidden === null ? [] : <Text dimColor>{hidden}</Text>}
      <Box marginTop={1}>
        <Text dimColor size="footnote">
          {generated === null ? 'Status time unknown.' : `Updated ${ago(now - generated)}.`}
        </Text>
      </Box>
      <Text dimColor size="footnote">{'≈ inferred, not read · ↻ reset'}</Text>
    </Box>
  )
}

function standingsTree(T: Table, look: Look, snapshot: StatusSnapshot | null, now: number,
                       inUse: StatusAccount | null): RenderElement {
  const { Box, Text } = T
  if (snapshot === null) {
    return <Box><Text dimColor>Reading WindowTally's status…</Text></Box>
  }
  if (snapshot.kind !== 'ok') {
    return (
      <Box flexDirection="column">
        <Text color="warning">{problemText(snapshot) ?? ''}</Text>
        {'path' in snapshot ? <Text dimColor>{`Status file: ${snapshot.path}`}</Text> : <Text> </Text>}
      </Box>
    )
  }
  const status = snapshot.status
  return (
    <Box flexDirection="column">
      {headLines(T, status, now)}
      {listed(status.accounts)
        .map(account => accountBlock(T, look, status, account, account.uuid === inUse?.uuid, now))}
      {foot(T, status, now)}
    </Box>
  )
}
