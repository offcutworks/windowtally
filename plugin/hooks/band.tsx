/**
 * The band above the prompt: every account's 5-hour and weekly standing, which account the desktop app and the CLI
 * use, and which to use next, drawn from the last status.json read.
 *
 * Per account: its name, cut at NAME_CUT characters with an ellipsis; its tags (`app` and `CLI` for the accounts in
 * use, `app closed` in place of `app` while the status reports the desktop app not running — which only a session the
 * app does not host reads, so only the terminal's band says it — and `next` for the recommended one); `renew 2d` in the warning colour while the user's renewal reminder finds its
 * recorded period ending within the reminder's days, or `plan ended` in its place while the account's bills record a
 * plan that has ended and none since (status.json's subscription state `ended`), dim, or in the warning colour while a
 * client uses the account; `5h` with the percentage and the time until the window resets (↻), or a mark for a window
 * not started; and `week` with the percentage and the weekday and time it resets (↻Sat 04:00), a week being at most
 * seven days long; then each per-model window the service gives the account — a model's own allowance inside the
 * week, Fable's, shown only on an account that has used the model — by the model's name, `Fable ≈24%`, its reset
 * left unsaid where it is the week's, and its warning colours at 80 % and 95 %, as its warnings are, its figure alone
 * with no meter on every band surface, the desktop's in-use line included (the panel draws its meter). An account
 * whose plan has ended and that neither client uses shows no figures (`windowsLeftOut`), on every band surface, the
 * folded card included, only `week ↻Sun 21:59`, the moment a renewal is planned around: it takes no readings, so its
 * figures are its last ones rolled forward through their resets to nothing, which would read as room left — the
 * reason the recommendation does not weigh it either. The service lists it after the others. One a client uses keeps
 * its figures, its readings keeping them live. ≈ marks a figure the service inferred rather than
 * read; a window's reset is marked only where no figure stands before it, and then only where its reset time was
 * inferred. A number at or past a warning threshold takes the theme's warning colour, past the second one its error
 * colour. An account with no 5-hour limit (status.json's state `no_limit`) shows no 5-hour window on any band surface:
 * its weekly window leads, and on the in-use line it takes the 5-hour window's place and scale. The panel still says
 * `no limit` for it. Details opens the panel, where every figure is spelt out and every name is whole.
 *
 * The account in use is the one the session's use is booked to, as the limit warnings judge it (status.ts,
 * accountInUse): the desktop app's in a session the app hosts, the CLI's otherwise. It stands apart from the others,
 * which follow it in the service's order. An account status.json marks hidden — one the user hid that neither client
 * uses — is on no line and in no card (`listed`).
 *
 * Two layouts, one per surface that raises the band:
 *   terminal  one line, cut at the band's edge, Details kept in place (bandTree), in the full words: `not started`,
 *             two spaces between an account's parts. The terminal draws one size, so the account in use, first on
 *             the line, is set apart by weight and colour alone: its name semibold in the theme's `claude` colour,
 *             the other accounts dim. The engine folds the band there itself (its `[-]`, ctrl+x ctrl+a), so the
 *             plugin draws no fold.
 *   desktop   two columns (desktopBandTree). The left holds the fold button, `Accounts ▾`, plain and dim, over
 *             Details, plain too but at full strength, so their first letters stand one over the other and Details
 *             keeps the second line however many lines the band takes. The right holds the account in use on a line
 *             of its own, an orange `● ` before its name, its 5-hour figure the band's largest text with a meter and
 *             a semibold countdown, its weekly window smaller with a smaller meter and a dim countdown, any
 *             per-model window's figure with no meter, then the fault flags; under it the
 *             other accounts, a grey `● ` (the same glyph at the same size, so the first name stands under the
 *             in-use name) before their compact words in smaller dim text: a dim `–` for a window not started, one
 *             space between an account's parts, `│ ` between accounts. With no account in use the flags take that
 *             line and the others' line follows. Nothing runs past the band's width: the in-use line's groups and
 *             the others' units wrap as wholes, and one wider than the room by itself wraps within itself.
 *             Folded, the band is the fold button, `Accounts ▸`, then the accounts the others' line would show — the
 *             account in use is left to Claude's own usage indicator — or, where there are none, the account in use,
 *             its dot orange, in the others' compact words on one line that ends in an ellipsis at the band's edge,
 *             then the fault flags.
 *             The accounts take only the room the button and the flags leave, a fold hiding figures, not faults, so
 *             the band stays one line unless the flags alone outgrow it and wrap. A pointer resting on the
 *             button reveals a card of every listed account in the compact words, which the desktop app lifts above the
 *             band (a hover card: a Box drawn absolute and hidden, shown by hover, inside the keyed Box of the fold
 *             button).
 *
 * What the desktop app does with a tree, measured in drawing the band (Claude Code 2.1.299, 2026-10-26), and which the
 * tree is shaped by: a Button draws its own `label`, `plain` and `dimColor` alone, never Text children, so no label is
 * bold or led by a hidden glyph; a Text coloured `transparent` is drawn in the ordinary colour and an empty drawing
 * holds no place, so alignment comes from structure and visible glyphs only; the app keeps space around every button,
 * so the fold glyph joins its label rather than standing in a button of its own; the app reshapes a row whose last
 * children are buttons into a block of text and a row of actions, so every Button stands in a Box of its own; and a
 * Text's `size` and `weight`, raw colours and drawings sized in pixels are drawn as given.
 */

import type { Elements, RenderElement } from 'claude-code'
import type { StatusAccount, StatusDocument, StatusScoped, StatusWindow, StatusSnapshot } from '../types'
import { scopedKind, thresholdsOf } from './alerts'
import { parseTime, percentText, span, when } from './text'

/** The elements every surface that draws the band carries. */
export type Table = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>

/** The desktop's, which draws the meters as well. */
export type DesktopTable = Table & Pick<Elements['desktop'], 'Svg'>

/** A status older than this means the service stopped writing (WindowTally's own `status` command warns at it). */
export const STALE_MS = 5 * 60_000

/** The longest name the band shows whole; a longer one is cut to this many characters and an ellipsis. */
export const NAME_CUT = 16

/**
 * The glyph that opens the in-use line, in the theme's `claude` colour, and the other accounts' line, dim; the panel
 * opens each account's block with it the same way.
 */
export const DOT = '● '

/**
 * The meters' fills: WindowTally's status fills (windowtally/palette.py's `good`, `warning` and `critical`, the same in
 * both themes), chosen by the window's warning figures as every surface's meters are. A drawing takes raw colours and
 * the plugin cannot read the app's theme, so the track is a translucent grey that shows on a light background and a
 * dark one alike.
 */
const METER_FILL = { normal: '#0ca30c', warning: '#fab219', error: '#d03b3b' } as const
const METER_TRACK = '#8a8880'
const METER_TRACK_OPACITY = 0.35

type Part = string | RenderElement

/**
 * How a window is drawn on the in-use line, and in every block of the panel: the 5-hour window large, the weekly one
 * small. A dim countdown takes no weight of its own.
 */
export type Scale = {
  figureSize: 'heading' | 'body' | 'footnote'
  figureWeight: 'bold' | 'semibold' | 'regular'
  countdownSize: 'body' | 'footnote'
  countdownDim: boolean
  countdownWeight: 'semibold' | 'regular'
  meter: { width: number; height: number }
}

/** The 5-hour window: the band's largest text, a meter beside it, a semibold countdown. Sizes in CSS pixels. */
export const FIVE_HOUR_SCALE: Scale = {
  figureSize: 'heading', figureWeight: 'bold', countdownSize: 'body', countdownDim: false, countdownWeight: 'semibold',
  meter: { width: 72, height: 8 },
}

/** The weekly window: smaller text, a smaller meter, a dim countdown. */
export const WEEKLY_SCALE: Scale = {
  figureSize: 'footnote', figureWeight: 'semibold', countdownSize: 'footnote', countdownDim: true,
  countdownWeight: 'regular', meter: { width: 44, height: 5 },
}

/**
 * A name as the band shows it: whole up to NAME_CUT characters, else cut there with an ellipsis. A character is what a
 * reader counts as one, a grapheme cluster, so no cut splits an accent from its letter or an emoji sequence; where the
 * engine has no segmenter, code points stand in.
 */
export function bandName(label: string): string {
  const Segmenter = (Intl as unknown as { Segmenter?: new (locale?: string, options?: { granularity: 'grapheme' }) => {
    segment: (text: string) => Iterable<{ segment: string }>
  } }).Segmenter
  const characters = Segmenter
    ? Array.from(new Segmenter(undefined, { granularity: 'grapheme' }).segment(label), piece => piece.segment)
    : [...label]
  return characters.length > NAME_CUT ? `${characters.slice(0, NAME_CUT).join('')}…` : label
}

/**
 * How a surface writes an account: the space between its parts, what stands for a window not started, and whether
 * every run is cut rather than wrapped (`cut`).
 */
type Words = { gap: string; notStarted: string; cut?: boolean }

/** The terminal's words, in full. */
const FULL: Words = { gap: '  ', notStarted: 'not started' }

/** The desktop's words, compacted so more accounts fit a line; the panel spells every window out. */
const COMPACT: Words = { gap: ' ', notStarted: '–' }

/**
 * The folded band's words: the compact ones, every run a Text of its own that never wraps (`cutRuns`). The desktop app
 * draws a Text cut at its end without wrapping, but every Text inside it as wrapping again, at the end of any run (its
 * bundle, 2.42304.0.0, 2026-10-31); runs each cut keep the line whole, and it ends in an ellipsis at the band's edge.
 */
const FOLDED: Words = { ...COMPACT, cut: true }

/** The props that keep a Text from wrapping where its run is cut, none where it is not. */
const cutProps = (cut: boolean | undefined) => (cut ? { wrap: 'truncate-end' as const } : {})

/** Runs that are cut: every bare string a Text of its own that never wraps, as `cutProps` makes the styled ones. */
function cutRuns(T: Table, parts: Part[]): Part[] {
  const { Text } = T
  return parts.map(part => (typeof part === 'string' && part ? <Text wrap="truncate-end">{part}</Text> : part))
}

/** The accounts a surface lists: every one but those status.json marks hidden, which no surface lists. */
export function listed(accounts: readonly StatusAccount[]): StatusAccount[] {
  return accounts.filter(account => !account.hidden)
}

/** The tag of an account whose bills record a plan that has ended and none since, the same in every surface's words. */
const PLAN_ENDED = 'plan ended'

/**
 * Whether the account's bills record a plan that has ended and none since (status.json's subscription state `ended`),
 * one of the accounts the recommendation does not weigh. A plan upcoming or no bill recorded is not one.
 */
function planEnded(account: StatusAccount): boolean {
  return account.subscription?.state === 'ended'
}

/**
 * Whether the band and the panel leave the account's figures out: its plan has ended and neither client uses it, so
 * it takes no readings and its figures are its last ones rolled forward through their resets, standing at nothing.
 */
export function windowsLeftOut(account: StatusAccount): boolean {
  return planEnded(account) && !account.isDesktop && !account.isCli
}

/** A weekly reset further off than this carries its date: its weekday is today's (windowtally_gui/live_model.py). */
const WEEK_DATED_AFTER_MS = 6 * 24 * 60 * 60_000

/** When a weekly window resets: `Sat 04:00`, or `Sat 14 Nov 04:00` more than six days away. */
export function weekMoment(reset: number, now: number): string {
  return when(reset, reset - now > WEEK_DATED_AFTER_MS)
}

/**
 * When a window resets, after ↻: the weekly window's weekday and time (`weekMoment`), the 5-hour window's time left
 * (`1h 05m`); `mark` (≈) where the reset time was inferred and no figure stands before it to say so.
 */
export function resetWords(kind: string, reset: number, now: number, mark = ''): string {
  return `↻${mark}${kind === 'five_hour' ? span(reset - now) : weekMoment(reset, now)}`
}

/** Two reset times this close name one moment: a per-model window resets with the weekly window. */
const SAME_RESET_MS = 60_000

/**
 * A per-model window (Fable's) as a window is drawn: its figure, ≈ where the service estimated it, and its reset only
 * where it is not the weekly window's, which it shares on every account seen so far, so the band does not say it twice.
 */
export function scopedWindow(scoped: StatusScoped, weekly: StatusWindow): StatusWindow {
  const own = parseTime(scoped.resetsAt)
  const week = parseTime(weekly.resetsAt)
  const shared = own !== null && week !== null && Math.abs(own - week) < SAME_RESET_MS
  return {
    state: scoped.state, percent: scoped.percent, resetsAt: shared ? null : scoped.resetsAt, asOf: scoped.asOf,
    estimated: scoped.estimated, exhaustsAt: null, anchorExact: true,
  }
}

/** The account's per-model windows, each with the kind it is coloured and warned by and the name it is shown by. */
export function scopedOf(account: StatusAccount): { name: string; kind: string; window: StatusWindow }[] {
  return (account.weekly.scoped ?? []).map(scoped => ({
    name: bandName(scoped.name), kind: scopedKind(scoped.name), window: scopedWindow(scoped, account.weekly),
  }))
}

/**
 * Whether the account has no 5-hour limit, so that its weekly window leads wherever it is shown: alone on the band,
 * before a 5-hour row saying `no limit` in the panel.
 */
export function weeklyLeads(account: StatusAccount): boolean {
  return account.fiveHour.state === 'no_limit'
}

export function levelColor(kind: string, value: number | null): 'warning' | 'error' | null {
  const [first, second] = thresholdsOf(kind) ?? []
  if (value === null || first === undefined) return null
  if (second !== undefined && value >= second) return 'error'
  return value >= first ? 'warning' : null
}

/** What stands in the band in place of the standings when status.json cannot give them. */
export function problemText(snapshot: StatusSnapshot): string | null {
  switch (snapshot.kind) {
    case 'ok':
      return snapshot.status.accounts.length ? null : 'WindowTally: no account is known yet.'
    case 'missing':
      return 'WindowTally: no status file yet; is the WindowTally service running?'
    case 'unreadable':
      return `WindowTally: the status file cannot be read: ${snapshot.problem}.`
    case 'unknown-version':
      return `WindowTally: the status file is version ${snapshot.version}, which this plugin does not read.`
    case 'no-home':
      return 'WindowTally: the environment names no home folder (USERPROFILE or HOME).'
  }
}

/**
 * ≈ for a reset time that was inferred: status.json's `estimated` covers the figure and the reset time together, and
 * `anchorExact` says which it was for the reset time; a file that does not say leaves `estimated` to stand for both.
 */
export function resetMark(window: StatusWindow): string {
  if (window.anchorExact !== undefined) return window.anchorExact ? '' : '≈'
  return window.estimated ? '≈' : ''
}

function windowPart(T: Table, name: string, kind: string, window: StatusWindow, now: number, words: Words): Part[] {
  const { Text } = T
  const cut = cutProps(words.cut)
  if (window.state === 'not_started') return [`${name} `, <Text dimColor {...cut}>{words.notStarted}</Text>]
  const reset = parseTime(window.resetsAt)
  const approx = window.estimated ? '≈' : ''
  const countdown = reset === null ? '' : ` ${resetWords(kind, reset, now)}`
  if (window.percent === null) {
    const state = window.state === 'running' ? 'running' : 'unknown'
    return [`${name} `, <Text dimColor {...cut}>{state}</Text>,
            reset === null ? '' : ` ${resetWords(kind, reset, now, resetMark(window))}`]
  }
  const color = levelColor(kind, window.percent)
  const figure = `${approx}${percentText(window.percent)}`
  return [`${name} `, color ? <Text color={color} {...cut}>{figure}</Text> : figure, countdown]
}

/**
 * The words an account's tags are written in: the band's short ones, the panel's full ones. `closed` is the desktop
 * app's tag while the status reports the app not running, which a session the app hosts never reads.
 */
export type TagWords = { desktop: string; closed: string; cli: string; next: string }

const SHORT_TAGS: TagWords = { desktop: 'app', closed: 'app closed', cli: 'CLI', next: 'next' }

export function tags(account: StatusAccount, status: StatusDocument, words: TagWords = SHORT_TAGS): string[] {
  const list: string[] = []
  if (account.isDesktop) list.push(status.desktopRunning === false ? words.closed : words.desktop)
  if (account.isCli) list.push(words.cli)
  if (account.uuid === status.recommended.account) list.push(words.next)
  return list
}

/** The accounts in use first, then the rest, each group in the service's order. */
export function bandOrder(accounts: readonly StatusAccount[]): StatusAccount[] {
  const inUse = accounts.filter(a => a.isDesktop || a.isCli)
  return [...inUse, ...accounts.filter(a => !inUse.includes(a))]
}

/**
 * How an account's name is set: `semibold` everywhere but the terminal, where the account in use is `in-use`,
 * semibold in the theme's `claude` colour, and the other accounts `plain`, their line dim.
 */
type Emphasis = 'semibold' | 'in-use' | 'plain'

/**
 * An account's name, its tags and its plan's tag — the renewal tag, or `plan ended`; `smallTags` sets the tags in the
 * smaller size, and `cut` keeps each styled run from wrapping (`cutProps`).
 */
function headingParts(T: Table, account: StatusAccount, status: StatusDocument, emphasis: Emphasis = 'semibold',
                      smallTags = false, cut = false): Part[] {
  const { Text } = T
  const props = cutProps(cut)
  const name = bandName(account.label)
  const accountTags = tags(account, status)
  const tagText = ` (${accountTags.join(', ')})`
  // `plan ended` first, so the tag always agrees with the figures `windowsLeftOut` leaves out; the service sets a
  // renewal only while a plan is in effect, so the two never compete. It is a warning only on an account a client
  // uses; on one set aside it is dim, as the account is.
  const planTag = planEnded(account)
    ? windowsLeftOut(account) ? <Text dimColor {...props}>{` ${PLAN_ENDED}`}</Text>
      : <Text color="warning" {...props}>{` ${PLAN_ENDED}`}</Text>
    : account.subscription?.renewSoon && account.subscription.daysLeft !== null
      ? <Text color="warning" {...props}>{` renew ${account.subscription.daysLeft}d`}</Text> : ''
  return [
    emphasis === 'plain' ? name
      : emphasis === 'in-use' ? <Text weight="semibold" color="claude" {...props}>{name}</Text>
      : <Text weight="semibold" {...props}>{name}</Text>,
    !accountTags.length ? ''
      : smallTags ? <Text dimColor size="footnote" {...props}>{tagText}</Text>
      : <Text dimColor {...props}>{tagText}</Text>,
    planTag,
  ]
}

/**
 * An account's windows: `5h ≈67% ↻50m  week 69% ↻Sat 04:00` in full, `5h ≈67% ↻50m week 69% ↻Sat 04:00`
 * compacted; with no 5-hour limit the weekly window alone, `week 69% ↻Sat 04:00`, the band showing no 5-hour window
 * for it; a per-model window after the weekly one, `Fable ≈24%`, its reset being the week's; where the band leaves the
 * figures out (`windowsLeftOut`), the week's reset alone, `week ↻Sun 21:59`, or nothing without one.
 */
function windowsParts(T: Table, account: StatusAccount, now: number, words: Words): Part[] {
  if (windowsLeftOut(account)) {
    const reset = parseTime(account.weekly.resetsAt)
    return reset === null ? [] : [`week ${resetWords('seven_day', reset, now, resetMark(account.weekly))}`]
  }
  const weekly = [
    ...windowPart(T, 'week', 'seven_day', account.weekly, now, words),
    ...scopedOf(account).flatMap(s => [words.gap, ...windowPart(T, s.name, s.kind, s.window, now, words)]),
  ]
  if (weeklyLeads(account)) return weekly
  return [...windowPart(T, '5h', 'five_hour', account.fiveHour, now, words), words.gap, ...weekly]
}

function accountParts(T: Table, account: StatusAccount, status: StatusDocument, now: number, words: Words,
                      emphasis: Emphasis = 'semibold'): Part[] {
  const heading = headingParts(T, account, status, emphasis, false, words.cut)
  const windows = windowsParts(T, account, now, words)
  return windows.length ? [...heading, words.gap, ...windows] : heading
}

/**
 * The faults the band flags beside the standings, one run each: every account at or near its limit, a stale status,
 * the source problems. A fold hides figures, never these.
 */
function faultFlags(T: Table, status: StatusDocument, now: number): RenderElement[] {
  const { Text } = T
  const flags: RenderElement[] = []
  // The countdown is marked ≈ only where the moment was inferred, as a window's countdown is.
  const relief = parseTime(status.recommended.reliefAt)
  if (relief !== null) {
    const moment = `${status.recommended.reliefExact ? '' : '≈'}${span(relief - now)}`
    flags.push(status.recommended.account === null
      ? <Text color="error">{`all accounts at their limit · first opens ↻${moment}`}</Text>
      : <Text color="warning">{`all accounts near their limit · room returns ↻${moment}`}</Text>)
  }
  const generated = parseTime(status.generatedAt)
  if (generated !== null && now - generated > STALE_MS) {
    flags.push(<Text color="warning">{`status ${span(now - generated)} old`}</Text>)
  }
  const problems = status.sourceErrors.length
  if (problems) {
    flags.push(<Text color="warning">{`${problems} source problem${problems === 1 ? '' : 's'}`}</Text>)
  }
  return flags
}

/** The accounts other than the one in use, in the service's order, those status.json marks hidden left out. */
function othersOf(status: StatusDocument, inUse: StatusAccount | null): StatusAccount[] {
  return bandOrder(listed(status.accounts)).filter(a => a.uuid !== inUse?.uuid)
}

/**
 * The terminal band's text: the account in use first, its name semibold in the `claude` colour, then the other
 * accounts dim, then what the reader should know about the standings' freshness. `inUse` is the session's account
 * (status.ts, accountInUse), one of the snapshot's accounts or null.
 */
export function lineParts(T: Table, snapshot: StatusSnapshot, now: number, inUse: StatusAccount | null): Part[] {
  const { Text } = T
  const problem = problemText(snapshot)
  if (problem !== null || snapshot.kind !== 'ok') return [<Text color="warning">{problem ?? ''}</Text>]
  const status = snapshot.status
  const others = othersOf(status, inUse)
  const parts: Part[] = inUse ? accountParts(T, inUse, status, now, FULL, 'in-use') : []
  for (const other of others) {
    if (parts.length) parts.push(<Text dimColor>{'  │  '}</Text>)
    parts.push(<Text dimColor>{accountParts(T, other, status, now, FULL, 'plain')}</Text>)
  }
  for (const flag of faultFlags(T, status, now)) parts.push('  ', flag)
  return parts
}

export function bandTree(T: Table, snapshot: StatusSnapshot, now: number, inUse: StatusAccount | null,
                         onDetails: () => void): RenderElement {
  const { Box, Text, Button } = T
  return (
    <Box flexDirection="row" gap={1}>
      <Box flexGrow={1} flexShrink={1}>
        <Text wrap="truncate-end">{lineParts(T, snapshot, now, inUse)}</Text>
      </Box>
      <Button key="details" label="Details" dimColor onPress={onDetails} />
    </Box>
  )
}

/** The fold button's label, folded and unfolded: the glyph after the word, so that Details' `D` stands under `A`. */
const FOLD_LABELS = { folded: 'Accounts ▸', unfolded: 'Accounts ▾' } as const

/**
 * The card a pointer resting on the folded button reveals: every listed account, its name and tags over its windows
 * (`windowsParts`), in the band's compact words; an account whose figures the band leaves out (`windowsLeftOut`) has
 * its name and tags over its week's reset.
 * The desktop app lifts it out of the band and places it above the button, sized and framed as its own hover cards;
 * the offset only stands for that where nothing lifts it.
 */
function accountCard(T: Table, status: StatusDocument, now: number): RenderElement {
  const { Box, Text } = T
  return (
    <Box position="absolute" bottom={1} display="none" hover={{ display: 'flex' }} flexDirection="column" gap={1}>
      {bandOrder(listed(status.accounts)).map(account => {
        const windows = windowsParts(T, account, now, COMPACT)
        return (
          <Box flexDirection="column">
            <Text>{headingParts(T, account, status)}</Text>
            {windows.length ? [<Text>{windows}</Text>] : []}
          </Box>
        )
      })}
    </Box>
  )
}

/** The button that folds and unfolds the desktop band, in a keyed Box: the hover scope of the card it holds, folded. */
function foldTag(T: Table, snapshot: StatusSnapshot, now: number, folded: boolean, onFold: () => void): RenderElement {
  const { Box, Button } = T
  const card = folded && snapshot.kind === 'ok' && listed(snapshot.status.accounts).length > 0
    ? [accountCard(T, snapshot.status, now)] : []
  return (
    <Box key="fold-tag" flexShrink={0}>
      <Button key="fold" label={folded ? FOLD_LABELS.folded : FOLD_LABELS.unfolded} plain dimColor onPress={onFold} />
      {card}
    </Box>
  )
}

/** One unit of the folded band: a Box that never shrinks, so the runs of its Text never break across lines. */
function unit(T: Table, parts: Part[]): RenderElement {
  const { Box, Text } = T
  return <Box flexShrink={0}><Text>{parts}</Text></Box>
}

/**
 * The folded band's accounts: the others, those the others' line shows unfolded, since Claude's own usage indicator
 * shows the account in use; where there are none, the account in use, its dot orange. One line in the compact words,
 * smaller and dim, every run cut rather than wrapped (FOLDED), so the line ends in an ellipsis at the band's edge. It
 * asks for no width of its own (width 0, growing), so it never moves a unit to a further line: it fills what the fold
 * button and the fault flags leave on the first line, and the flags, the band's other units, wrap onto a further line
 * only when they do not fit beside the button by themselves.
 */
function foldedAccounts(T: Table, status: StatusDocument, now: number, inUse: StatusAccount | null): RenderElement[] {
  const { Box, Text } = T
  const others = othersOf(status, inUse)
  const accounts = others.length ? others : inUse ? [inUse] : []
  if (!accounts.length) return []
  const parts = cutRuns(T, accounts.flatMap((account, index) =>
    [index ? ' │ ' : '', ...accountParts(T, account, status, now, FOLDED)]))
  return [
    <Box key="folded-accounts" flexDirection="row" alignItems="flex-start" width={0} flexGrow={1} flexShrink={1}
         minWidth={0}>
      <Box flexShrink={0}>{others.length ? <Text dimColor>{DOT}</Text> : <Text color="claude">{DOT}</Text>}</Box>
      <Box flexShrink={1} minWidth={0} overflow="hidden">
        <Text wrap="truncate-end" dimColor size="footnote">{parts}</Text>
      </Box>
    </Box>,
  ]
}

/** Where status.json gives no standings, its problem, in their place. */
function problemUnit(T: Table, snapshot: StatusSnapshot): RenderElement[] {
  const { Box, Text } = T
  const problem = problemText(snapshot)
  if (problem === null && snapshot.kind === 'ok') return []
  return [<Box flexShrink={1}><Text color="warning">{problem ?? ''}</Text></Box>]
}

/**
 * One group of the in-use line, which wraps as a whole beside the others; only a group wider than the room by itself
 * shrinks, its parts then wrapping within it.
 */
export function group(T: Table, parts: Part[]): RenderElement {
  const { Box } = T
  return (
    <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap="xs" rowGap="xs" flexShrink={1}>
      {parts}
    </Box>
  )
}

/** A meter of `percent` used, at `size` CSS pixels, filled by the window's warning figures. */
export function meter(T: DesktopTable, kind: string, percent: number, size: Scale['meter'], alt: string): RenderElement {
  const { Svg } = T
  const { width, height } = size
  const used = Math.max(0, Math.min(100, percent))
  const filled = Math.round((width * used) / 100)
  const fill = METER_FILL[levelColor(kind, percent) ?? 'normal']
  const radius = height / 2
  const source = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`
    + `<rect width="${width}" height="${height}" rx="${radius}" fill="${METER_TRACK}" fill-opacity="${METER_TRACK_OPACITY}"/>`
    + (filled ? `<rect width="${filled}" height="${height}" rx="${radius}" fill="${fill}"/>` : '')
    + '</svg>'
  return <Svg source={source} alt={alt} width={width} height={height} />
}

/**
 * How `windowFigure` draws: `meters`, the table of a surface that draws an Svg, or null where none is drawn (the
 * terminal); `notStarted` the word for a window not started, drawn dim at the countdown's size, where the band draws a
 * dim `–` at the figure's.
 */
export type FigureOptions = { meters: DesktopTable | null; notStarted?: string }

/**
 * A window's figure at its scale, with a meter and its reset (`resetWords`): the time left for the 5-hour window, the
 * weekday and time for the weekly one. A window not started shows a dim `–`, or the word the options give, over an
 * empty meter; one with no figure (running, unknown) its state's word and its reset, which is marked ≈ only where its
 * reset time was inferred, and no meter, having nothing to fill it with. The 5-hour
 * window of an account with no 5-hour limit says `no limit`, dim at the countdown's size, with no meter: an empty one
 * would read as a window at zero.
 */
export function windowFigure(T: Table, title: string, kind: string, window: StatusWindow, now: number, scale: Scale,
                             options: FigureOptions): Part[] {
  const { Text } = T
  const parts: Part[] = []
  const gauge = (percent: number, alt: string) => {
    if (options.meters) parts.push(meter(options.meters, kind, percent, scale.meter, alt))
  }
  const reset = parseTime(window.resetsAt)
  const countdown = (text: string) => scale.countdownDim
    ? <Text size={scale.countdownSize} dimColor tabular>{text}</Text>
    : <Text size={scale.countdownSize} weight={scale.countdownWeight} tabular>{text}</Text>
  if (window.state === 'not_started') {
    parts.push(options.notStarted === undefined
      ? <Text size={scale.figureSize} weight={scale.figureWeight} dimColor>{'–'}</Text>
      : <Text size={scale.countdownSize} dimColor>{options.notStarted}</Text>)
    gauge(0, `${title} not started`)
    return parts
  }
  if (window.state === 'no_limit') {
    parts.push(<Text size={scale.countdownSize} dimColor>{'no limit'}</Text>)
    return parts
  }
  if (window.percent === null) {
    parts.push(<Text size={scale.countdownSize} dimColor>{window.state === 'running' ? 'running' : 'unknown'}</Text>)
    if (reset !== null) parts.push(countdown(resetWords(kind, reset, now, resetMark(window))))
    return parts
  }
  const figure = `${window.estimated ? '≈' : ''}${percentText(window.percent)}`
  const color = levelColor(kind, window.percent)
  parts.push(color
    ? <Text size={scale.figureSize} weight={scale.figureWeight} tabular color={color}>{figure}</Text>
    : <Text size={scale.figureSize} weight={scale.figureWeight} tabular>{figure}</Text>)
  gauge(window.percent, `${title} ${figure} used`)
  if (reset !== null) parts.push(countdown(resetWords(kind, reset, now)))
  return parts
}

/**
 * One window of the account in use, at its scale: its name, then its figure (`windowFigure`), with a meter where
 * `meters` gives the table to draw it, none where it is null.
 */
function windowGroup(T: Table, name: string, title: string, kind: string, window: StatusWindow, now: number,
                     scale: Scale, meters: DesktopTable | null): Part[] {
  const { Text } = T
  return [<Text dimColor size="footnote">{name}</Text>,
          ...windowFigure(T, title, kind, window, now, scale, { meters })]
}

/** The line the account in use stands on, or the flags alone where none is: groups that wrap as wholes. */
function groupLine(T: Table, key: string, groups: RenderElement[]): RenderElement {
  const { Box } = T
  return (
    <Box key={key} flexDirection="row" flexWrap="wrap" alignItems="center" columnGap="md" rowGap="xs" flexShrink={1}>
      {groups}
    </Box>
  )
}

/**
 * The account in use on a line of its own: the orange dot and its name, its 5-hour window, its weekly window, each
 * with a meter, any per-model window's figure without one, then the fault flags, each a group that wraps as a whole,
 * so the in-use name keeps its place over the others' names. With no 5-hour limit the weekly window leads at the
 * 5-hour window's scale and no 5-hour window is shown.
 */
function inUseLine(T: DesktopTable, account: StatusAccount, status: StatusDocument, now: number,
                   flags: RenderElement[]): RenderElement {
  const { Text } = T
  const leads = weeklyLeads(account)
  const fiveHour = leads ? [] : [group(T, windowGroup(T, '5h', '5-hour window', 'five_hour', account.fiveHour, now,
                                                      FIVE_HOUR_SCALE, T))]
  const weekly = group(T, windowGroup(T, 'week', 'weekly window', 'seven_day', account.weekly, now,
                                      leads ? FIVE_HOUR_SCALE : WEEKLY_SCALE, T))
  const scoped = scopedOf(account).map(s => group(T, windowGroup(T, s.name, `${s.name} allowance`, s.kind, s.window,
                                                                 now, WEEKLY_SCALE, null)))
  return groupLine(T, 'in-use', [
    group(T, [<Text>{[<Text color="claude">{DOT}</Text>, ...headingParts(T, account, status, 'semibold', true)]}</Text>]),
    ...fiveHour, weekly, ...scoped,
    ...flags,
  ])
}

/**
 * The other accounts: a dim dot, the same glyph at the same size as the in-use dot, then their units in the compact
 * words, smaller and dim, which wrap as wholes beside it so every line of them starts there; a unit wider than the
 * room by itself wraps within itself.
 */
function othersLine(T: Table, accounts: readonly StatusAccount[], status: StatusDocument, now: number): RenderElement {
  const { Box, Text } = T
  return (
    <Box key="others" flexDirection="row" alignItems="flex-start">
      <Box flexShrink={0}><Text dimColor>{DOT}</Text></Box>
      <Box key="others-units" flexDirection="row" flexWrap="wrap" columnGap={1} flexGrow={1} flexShrink={1}>
        {accounts.map((account, index) => (
          <Box flexShrink={1}>
            <Text dimColor size="footnote">{[index ? '│ ' : '', ...accountParts(T, account, status, now, COMPACT)]}</Text>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

/** The right column's lines: the in-use line, or the flags alone where no account is in use, over the others' line. */
function accountLines(T: DesktopTable, status: StatusDocument, now: number, inUse: StatusAccount | null): RenderElement[] {
  const others = othersOf(status, inUse)
  const flags = faultFlags(T, status, now).map(flag => group(T, [flag]))
  const lines: RenderElement[] = []
  if (inUse) lines.push(inUseLine(T, inUse, status, now, flags))
  else if (flags.length) lines.push(groupLine(T, 'flags', flags))
  if (others.length) lines.push(othersLine(T, others, status, now))
  return lines
}

/**
 * The desktop band. Unfolded: the left column, the fold button over Details, each in a Box of its own (a row whose
 * last child is a Button would be reshaped by the desktop app); the right, the account lines, or status.json's
 * problem where it gives no standings. Folded: the fold button, the folded accounts (foldedAccounts) and the fault
 * flags in one wrapping area, each flag after an account or another flag opening with `│ `, with no Details; or the
 * button and status.json's problem.
 */
export function desktopBandTree(T: DesktopTable, snapshot: StatusSnapshot, now: number, folded: boolean,
                                inUse: StatusAccount | null, onDetails: () => void, onFold: () => void): RenderElement {
  const { Box, Text, Button } = T
  if (folded) {
    let line: RenderElement[]
    if (snapshot.kind === 'ok' && problemText(snapshot) === null) {
      const accounts = foldedAccounts(T, snapshot.status, now, inUse)
      const flags = faultFlags(T, snapshot.status, now)
        .map((flag, index) => unit(T, index || accounts.length ? [<Text dimColor>{'│ '}</Text>, flag] : [flag]))
      line = [...accounts, ...flags]
    } else {
      line = problemUnit(T, snapshot)
    }
    return (
      <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
        <Box key="units" flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={1} flexGrow={1}
             flexShrink={1} minWidth={0}>
          {foldTag(T, snapshot, now, true, onFold)}
          {line}
        </Box>
      </Box>
    )
  }
  const lines = snapshot.kind === 'ok' && problemText(snapshot) === null
    ? accountLines(T, snapshot.status, now, inUse) : problemUnit(T, snapshot)
  return (
    <Box flexDirection="row" alignItems="flex-start" columnGap={1}>
      <Box key="controls" flexDirection="column" alignItems="flex-start" rowGap="xs" flexShrink={0}>
        {foldTag(T, snapshot, now, false, onFold)}
        <Box key="details-holder" flexShrink={0}>
          <Button key="details" label="Details" plain onPress={onDetails} />
        </Box>
      </Box>
      <Box key="accounts" flexDirection="column" rowGap="xs" flexGrow={1} flexShrink={1}>
        {lines}
      </Box>
    </Box>
  )
}
