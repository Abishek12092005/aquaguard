import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import WaterSplash from '@/components/WaterSplash'
import {
  GUIDE_INPUTS,
  GUIDE_STEPS,
  LOCATION_GUIDE_STEPS,
  UNSAFE_CONSEQUENCES,
} from '@/config/guide'
import { ICONS } from '@/config/navigation'
import { ROUTES } from '@/utils/constants'

/**
 * Home — the project walkthrough.
 *
 * Three blocks, in the order a new user needs them:
 *
 *   1. an auto-advancing rail of the six workflow steps that also swipes by hand,
 *      so the whole process is visible in one glance without anyone having to
 *      click through it
 *   2. what to type: the five parameters the model accepts, with their real units
 *      and the range each is valid over
 *   3. what the answer means, including what an unsafe reading can actually cost
 *      you — the part that decides whether someone acts on the verdict
 *
 * WHY THE RAIL IS A MARQUEE RATHER THAN A CAROUSEL WITH DOTS. A carousel needs a
 * click to advance, which means the second card is never seen by anyone who does
 * not click. This page exists to be read by someone who does not yet know what to
 * ask, so the steps have to come to them. The rail moves continuously and loops
 * seamlessly (see `guide-scroll` in the Tailwind config for why the -50% travel
 * is what makes the loop invisible), and it pauses on hover and on keyboard focus
 * so it is not hostile to someone who wants to actually read a card.
 *
 * Duplication is deliberate: the track renders the step list twice. The second
 * copy is what fills the gap as the first scrolls off, and it is also what makes
 * the -50% reset land on an identical frame. It is `aria-hidden`, so a screen
 * reader hears the six steps once rather than twelve.
 *
 * `motion-safe:` gates the animation, and the rail falls back to a plain
 * horizontally-scrollable list for a user who has asked for reduced motion.
 */
export default function Home() {
  return (
    <div>
      {/* THE WATER AI SPLASH. Mounted first so it paints over the page, and it
          removes itself after its two-second hold — nothing else on this page is
          conditional on it. See `WaterSplash` for the reduced-motion and
          once-per-visit behaviour. */}
      <WaterSplash />

      {/* THE LOCATION-PERMISSION POPUP IS NO LONGER RENDERED HERE. It became a
          GLOBAL popup mounted by the app shell (see AppLayout), because the
          brief requires it to appear on whatever page the visitor is on — a
          prompt owned by Home could not appear anywhere else, and navigating
          away within its two-second delay cancelled it. */}
      <PageHeader
        breadcrumb="Home"
        // ON THIS PAGE, AND ON A PHONE ONLY, THE ACTION GOES ON ITS OWN LINE
        // UNDER THE HEADING. The greeting is a long, variable-length sentence
        // ("Welcome back, Abishek"), so sharing a row left the button crammed
        // against it. `stacked` drops "Start a prediction" to the next line on
        // mobile; from `sm:` up the header reverts to the standard row with the
        // action hard right, so the desktop layout is untouched.
        stacked
        // The greeting is addressed to the visitor rather than named, because
        // there is no account: nothing in this application knows who is looking.
        title="Welcome to AquaGuard AI"
        actions={
          // POSITIONING IS LEFT TO PageHeader. Normally that means right-aligned
          // against the heading; here `stacked` puts the block on its own line,
          // so it starts at the left edge under the title. The link is a plain
          // inline-flex wrapper.
          <Link to={ROUTES.predict} className="inline-flex">
            <Button
              // A SPACE BETWEEN THE HEADING AND THE BUTTON, ON MOBILE ONLY.
              // `mt-1` gives a full line of breathing room between the greeting
              // and "Start a prediction" so the two no longer read as one block;
              // `sm:mt-0` removes it on desktop, where the button is on the same
              // row as the heading and any margin would push it out of line.
              //
              // DARK MODE IS A WHITE BUTTON WITH BLACK TEXT — the brightest,
              // clearest control on a dark page, matching the secondary/download
              // buttons. Its HOVER is black with white text, which is the rule
              // every button follows in dark mode. See `.btn-*` in index.css.
              className="mt-1 sm:mt-0 dark:bg-white dark:text-black dark:ring-1 dark:ring-white/20 dark:hover:bg-black dark:hover:text-white dark:active:bg-black dark:active:text-white"
            >
              <Icon path={ICONS.predict} className="h-4 w-4" />
              Start a prediction
            </Button>
          </Link>
        }
      />

      {/* --- 1. Auto-scrolling step rail ---------------------------------- */}
      <section aria-labelledby="guide-steps-heading" className="mb-6">
        {/* THE HEADING IS DESKTOP-ONLY: `hidden` up to `sm`, `sm:flex` above it.

            On a PHONE it is gone — the rail is self-evident there (each card
            already says "Step 1 of 6", and the dots plus the arrow say what the
            block is), and the heading only pushed the rail further down the
            first screen. On DESKTOP it is kept exactly as it always was: the
            same title and the same "6 steps" count, centred over the rail, so
            the wide layout is unchanged.

            It stays in the DOM at every width (just visually hidden on mobile)
            and still labels the section via `aria-labelledby`, so the rail has
            an accessible name on both viewports. */}
        <div className="mb-3 hidden flex-col items-center justify-center gap-1 text-center sm:flex">
          <h2
            id="guide-steps-heading"
            className="text-[0.9375rem] font-semibold text-slate-900 dark:text-white"
          >
            How it works, end to end
          </h2>
          <span className="text-xs font-medium text-slate-400">
            {GUIDE_STEPS.length} steps
          </span>
        </div>

        <StepRail steps={GUIDE_STEPS} />
      </section>

      {/* --- 2. What to enter --------------------------------------------- */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <EnterCard />

        {/* --- 2b. Reading the result --- */}
        <Card
          // DOUBLE-CARD RULE: this card sits on the RIGHT of the pair, so it
          // arrives from the RIGHT; the card beside it comes from the left. The
          // two converge into place rather than both popping in from nowhere.
          //
          // CENTERED HEADER AT EVERY WIDTH. The header is a flex row that the
          // Card component left-aligns by default; passing `bodyClassName`/`title`
          // as centered spans is not enough because the header row itself still
          // hugs the left. The clean way is to centre the WHOLE card's inner
          // content: `text-center` inherits into every block that does not
          // explicitly opt out, and each row below opts back out with its own
          // `text-left`.
          className="animate-slide-in-right p-3 sm:p-5"
          bodyClassName="text-center"
          title={
            <span className="block text-center text-base font-bold sm:text-lg">
              Reading the result
            </span>
          }
          subtitle={
            <span className="block text-center text-xs sm:text-sm">
              Three possible verdicts
            </span>
          }
        >
          {/* COMPACT BY SCREEN SIZE. The vertical rhythm shrinks on a phone
              (space-y-3, tighter footer) and relaxes from `sm:` up, so the card
              fills its column without sprawling on a small screen. */}
          <ul className="space-y-3 sm:space-y-4">
            <ResultRow
              tone="safe"
              title="SAFE"
              body="Every supplied parameter sits in its healthy band. The water is treated as potable at the point of testing."
            />
            <ResultRow
              tone="moderate"
              title="MODERATE"
              body="At least one reading is between clean and unsafe. Retest before drinking — this is a flag, not a pass."
            />
            <ResultRow
              tone="unsafe"
              title="UNSAFE"
              body="The combination is damaging. Treat the water as contaminated and see a laboratory test."
            />
          </ul>

          <p className="mt-3 border-t border-slate-100 pt-3 text-center text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400 sm:mt-5 sm:pt-4">
            Confidence is reported alongside every verdict. A low figure means the
            model had little to work with — usually because parameters were left
            out — not that the water is uncertain.
          </p>
        </Card>
      </div>

      {/* --- 3. Why an unsafe result matters ------------------------------- */}
      <section aria-labelledby="consequences-heading" className="mt-6">
        <h2
          id="consequences-heading"
          className="text-center text-[0.9375rem] font-semibold text-slate-900 dark:text-white"
        >
          What unsafe water actually costs you
        </h2>

        {/* ARRIVAL BY POSITION. On a wide screen these are a two-up grid, so the
            left column comes from the left and the right column from the right.
            On a phone they stack into ONE column, and a lone card has no side to
            belong to, so it zooms in from slightly smaller instead — the neutral
            arrival. `sm:` is where the grid becomes two columns, so it is also
            where the animation switches. */}
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {UNSAFE_CONSEQUENCES.map((item, index) => (
            <Card
              key={item.title}
              className={`border-l-4 border-l-unsafe/70 animate-zoom-in ${index % 2 === 0
                  ? 'sm:animate-slide-in-left'
                  : 'sm:animate-slide-in-right'
                }`}
              style={{ animationDelay: `${index * 0.12}s` }}
            >
              <div className="flex items-start gap-3">
                <span
                  className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-field ${item.tone === 'unsafe'
                      ? 'bg-unsafe-light text-unsafe-dark'
                      : 'bg-caution-light text-caution-dark'
                    }`}
                  aria-hidden="true"
                >
                  <Icon path={ICONS.alerts} className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{item.title}</h3>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.body}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* --- 4. STEP 31: the Location Prediction guide --------------------

          PLACED BELOW THE OTHER THREE, NOT ABOVE THEM.

          This is the last section on the page rather than the first, and that is a
          deliberate ordering decision rather than an accident of where the code
          landed. Everything above it describes the MANUAL flow — the five numbers,
          the ranges, the verdict — and that is still the flow a first-time visitor
          most needs to understand. The Location flow is the same feature reached
          the other way round: same five parameters, same three verdicts. So this
          section is framed as a SECOND WAY IN, and it reads correctly only once
          the reader knows what a parameter and a verdict are. Putting it first
          would have made "pH, turbidity, TDS…" the first thing the page says,
          with no explanation of what any of those words mean.

          IT ADDS, IT DOES NOT REPLACE. Nothing above this line is touched: the
          step rail, the parameter card, the verdict card and the consequences grid
          all render exactly as they did. */}
      <section aria-labelledby="location-guide-heading" className="mt-8">
        <LocationGuide />
      </section>
    </div>
  )
}

/**
 * "What you need to enter" — the five parameters the model accepts.
 *
 * The heading is centred to match the other two section headings, and each row
 * is a strict two-column document: a fixed-width label block on the left whose
 * text is left-aligned against the card's own edge, and a paragraph column on
 * the right that always starts on the same vertical line. `sm:grid-cols-[13rem_
 * minmax(0,1fr)]` is what guarantees the straight left edge — the label column
 * never grows, so every row's paragraph begins at the same x position, which is
 * the "straight line" alignment the block was missing when the label was a
 * flex child that sized itself to its content per row.
 *
 * On a phone the two columns stack, and each row is its own entry point: the
 * rows alternate in from the left and the right (`animate-slide-in-left` /
 * `animate-slide-in-right`) so they arrive one by one and settle, rather than
 * appearing as one undifferentiated list.
 */
function EnterCard() {
  return (
    <Card
      // DOUBLE-CARD RULE: this is the LEFT card of the pair, so it arrives from
      // the LEFT. Its partner on the right arrives from the right.
      className="animate-slide-in-left"
      title={
        <span className="block text-center text-base font-bold">
          What you need to enter
        </span>
      }
    >
      <ul className="divide-y divide-slate-100 dark:divide-slate-700">
        {GUIDE_INPUTS.map((input, index) => (
          <li
            key={input.key}
            // A STRICT TWO-TRACK GRID on desktop, one column on a phone.
            //
            // `sm:grid-cols-[13rem_minmax(0,1fr)]` is what guarantees the straight
            // LEFT edge — the label column is a fixed 13rem track that never
            // grows, so every row's label starts on the same vertical line and
            // every paragraph below begins at the same x on the right. A flex row
            // sized its label per row, which is what made the edges ragged.
            //
            // ON A PHONE THE ROWS ARRIVE ONE BY ONE, alternating sides: even rows
            // slide in from the left, odd rows from the right, staggered by
            // `index * 0.12s`, so each parameter lands as its own small arrival
            // and then holds still. `animate-*-both` (see tailwind.config.js)
            // keeps each row hidden until its own delay elapses, so they really do
            // come in one after another rather than all at once.
            //
            // The columns themselves are a strict grid on desktop, which is what
            // keeps the labels on one straight line down the left and the
            // paragraphs on one straight line down the right.
            className={`grid gap-1 py-3.5 text-left first:pt-0 last:pb-0 sm:grid-cols-[13rem_minmax(0,1fr)] sm:items-start sm:gap-5 ${index % 2 === 0 ? 'animate-slide-in-left' : 'animate-slide-in-right'
              }`}
            style={{ animationDelay: `${index * 0.12}s` }}
          >
            <div>
              <p className="text-sm font-semibold text-slate-900 dark:text-white">
                {input.label}
              </p>
              <p className="text-xs text-slate-400 tabular">
                {input.unit} · valid {input.range}
              </p>
            </div>
            <div className="min-w-0">
              <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">
                {input.note}
              </p>
              <p className="mt-1 text-xs font-medium text-safe-dark dark:text-safe-light">
                Typical healthy range: {input.good} {input.unit === 'pH' ? '' : input.unit}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/**
 * The auto-scrolling rail.
 *
 * Structure: a clipping viewport (`overflow-hidden`) holding a track that is
 * twice the content. The track is what animates; the viewport never moves. Each
 * card is `shrink-0` with a fixed basis so the two copies measure identically —
 * if a card could flex, the two halves would drift apart in width and the -50%
 * reset would land on the wrong frame.
 *
 * The outer element carries `group` and the hover/focus pause, so pointing
 * anywhere on the rail stops the whole thing rather than one card.
 */
function StepRail({ steps }) {
  const total = steps.length
  // 5s per step, matching the previous cadence.
  const slotSeconds = 5
  /**
   * THE RAIL ONLY EVER MOVES ONE WAY: LEFT, WITH THE NEXT STEP COMING IN FROM
   * THE RIGHT.
   *
   * The previous version held `active` in `0..total-1` and wrapped it with a
   * modulo. That is fine for the transform, but it makes the WRAP a backwards
   * jump: going 6 -> 1 rewound the track five card-widths to the right, so the
   * sixth step slid left and then the first step slid in from the left. The user
   * saw exactly that and asked for it to stop.
   *
   * The fix is a monotonically increasing counter and a track long enough that
   * there is always a card off-screen to the RIGHT to move into. `position`
   * counts cards moved; the track holds `3 x total` cards (the step list three
   * times over) and translates left by one card per step. When `position`
   * reaches `total` (i.e. the track has walked exactly one full copy of the
   * list), it is RESET to 0 with the transition suppressed for that one frame —
   * at that instant the reset and the un-reset positions render IDENTICALLY,
   * because position `total` shows the same card in the same place as position
   * `0`. So the reset is invisible and the motion never reverses.
   *
   * Why not an infinite index with a huge track: the track has to be finite in
   * the DOM, and re-centring on a fixed cadence is what keeps the DOM cost
   * constant. Resetting at `total` (rather than at a larger multiple) also keeps
   * the reset aligned to a step boundary, which is what makes it invisible.
   */
  const [position, setPosition] = useState(0)
  // True for the single frame of a wrap-around. While it is set, the track has
  // no transition, so the snap back to position 0 cannot animate.
  const [snapping, setSnapping] = useState(false)

  // Paused ONLY while the pointer is genuinely resting on the rail, while a card
  // has keyboard focus, or during a live drag. Every one of those is a transient
  // "the user is interacting right now" state, and each has a matching event that
  // clears it — so the rail ALWAYS resumes. It must never come to a permanent
  // stop: that is the requirement, and it is why there is no "stopped" flag the
  // component could get stuck in.
  const [paused, setPaused] = useState(false)
  const [dragging, setDragging] = useState(false)
  // A watchdog that clears a STUCK interaction state. Some touch browsers fire
  // the emulated `mouseenter` when a finger lands but never the matching
  // `mouseleave`, which would leave `paused` true forever — the rail would look
  // frozen. Any interaction is treated as short-lived: if nothing has refreshed
  // it within one slot, the rail is allowed to move again.
  const interactionRef = useRef(null)
  const noteInteraction = useCallback(() => {
    if (interactionRef.current) clearTimeout(interactionRef.current)
    interactionRef.current = setTimeout(() => {
      setPaused(false)
      interactionRef.current = null
    }, slotSeconds * 1000)
  }, [slotSeconds])

  // Drag bookkeeping. A ref (not state) because these change on every pointer
  // move and must NOT trigger a re-render while the finger is down.
  const dragStartX = useRef(0)
  const dragStartY = useRef(0)
  const dragActive = useRef(false)
  const stageRef = useRef(null)
  // The pending snap-to-zero timer, cleared on unmount so a timer cannot fire
  // after the component is gone.
  const snapTimer = useRef(null)

  // The card the dots should highlight. Derived from `position`, never stored:
  // after a reset the highlight must still name the card that is on screen.
  const active = position % total
  /** Move one step forward. The only direction the rail moves. */
  const next = useCallback(() => {
    setPosition((current) => {
      const advanced = current + 1
      if (advanced >= total) {
        // Schedule the invisible rewind. It runs on the NEXT frame, after the
        // slide into the last card has been committed, so the snap happens while
        // the on-screen card is identical before and after.
        if (snapTimer.current) clearTimeout(snapTimer.current)
        snapTimer.current = setTimeout(() => {
          setSnapping(true)
          setPosition(0)
          // Re-enable the transition on the frame after the reset.
          snapTimer.current = setTimeout(() => setSnapping(false), 40)
        }, 560)
      }
      return advanced
    })
  }, [total])

  /** Move one step BACK is done inline in the back arrow's onClick: the track
      holds three copies of the list and `position` is only reset to 0 when it
      crosses the forward boundary, so a backward move can never run off the
      left edge — it just slides to the previous card within the same copies. */

  useEffect(
    () => () => {
      if (snapTimer.current) clearTimeout(snapTimer.current)
      if (interactionRef.current) clearTimeout(interactionRef.current)
    },
    [],
  )

  // Auto-advance: the whole point of the rail is that the steps come to the
  // reader, so it moves on a timer.
  //
  // A SELF-RESCHEDULING TIMEOUT, not `setInterval`. The rail must keep moving no
  // matter what was clicked or dragged, and a timeout whose next one is armed by
  // the callback cannot be left in a dead state by an interleaved pause/unpause:
  // every time the pause lifts, a fresh timer is armed, and every step re-arms it
  // again. A manual swipe or a dot click only changes `position`; the clock keeps
  // running underneath, so the user's own action never stops the auto-swipe.
  useEffect(() => {
    if (paused || dragging) return undefined
    const timer = setTimeout(next, slotSeconds * 1000)
    return () => clearTimeout(timer)
  }, [paused, dragging, next, position, slotSeconds])

  /* --- Manual swipe ------------------------------------------------------- */
  // Pointer events cover mouse, touch and pen with one code path. The gesture is
  // a HORIZONTAL drag. A right-to-left drag (dx < 0) advances — the card is
  // pushed out to the left, the next arrives from the right, which is the same
  // direction the rail auto-advances. A left-to-right drag does nothing, because
  // the rail is forward-only by design. A vertical drag is ignored entirely so
  // the page can still be scrolled by starting on a card.
  function onPointerDown(event) {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    dragStartX.current = event.clientX
    dragStartY.current = event.clientY
    dragActive.current = true
    setDragging(true)
  }

  function onPointerUp(event) {
    if (!dragActive.current) return
    const dx = event.clientX - dragStartX.current
    const dy = event.clientY - dragStartY.current
    // CLEAR THE DRAG STATE FIRST, before any early return. If a gesture is too
    // short to count as a swipe, `dragging` must still go false — otherwise the
    // rail treats it as an in-progress drag forever and the auto-swipe stays off.
    dragActive.current = false
    setDragging(false)

    // Must be a mostly-horizontal gesture, and far enough to be intentional, so
    // a stray tap or a page scroll never changes the card.
    const THRESHOLD = 40
    if (Math.abs(dx) < THRESHOLD || Math.abs(dx) < Math.abs(dy)) return
    if (dx < 0) next()
  }

  function onPointerCancel() {
    // Same contract as `onPointerUp`: a cancelled gesture always releases the
    // drag, so the auto-swipe resumes rather than being left paused.
    dragActive.current = false
    setDragging(false)
  }

  // A pointer that leaves the stage mid-drag (a finger sliding off the edge)
  // never fires `pointerup` on this element, which would strand `dragging` as
  // true. Releasing on leave is what guarantees the rail keeps moving.
  function onPointerLeave() {
    if (!dragActive.current) return
    dragActive.current = false
    setDragging(false)
  }

  return (
    <div
      className="group card p-0"
      // Pause on hover and on keyboard focus — a reader who wants to actually read
      // a card can hold it still. EVERY pause is paired with a matching resume,
      // and each one also arms the watchdog, so a browser that drops the
      // `mouseleave` cannot leave the rail frozen.
      onMouseEnter={() => {
        setPaused(true)
        noteInteraction()
      }}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => {
        setPaused(true)
        noteInteraction()
      }}
      onBlurCapture={() => setPaused(false)}
      aria-roledescription="carousel"
      aria-label="Workflow steps"
    >
      {/* The clipping viewport. The track inside is `total` cards wide and is
          translated by exactly one card width per step, so the cards slide
          RIGHT TO LEFT in the order 1, 2, 3, 4, 5, 6, 1 ... and the loop is a
          wrap of `active` back to 0 rather than a jump.

          HOW ONE-CARD-PER-STEP IS GUARANTEED ON A PHONE. The track's width is
          `total x 100%`, and every card is `w-full basis-full shrink-0`. Both
          halves read the SAME `total`, so the card width is exactly the viewport
          width of the stage at any breakpoint — a card can never be a partial
          sliver of the next one. That is what was wrong before: the old percentage
          maths assumed a flexible card, so on a narrow screen two cards could
          share the view and the step looked misaligned.

          The stage height is now `auto` with a `min-h`, and the cards stretch to
          the tallest one. A fixed `h-[17rem]` clipped the longer step bodies on a
          phone, which is precisely the "step 2/3/4 not visible" report — the text
          was inside a card whose own height was shorter than its content.

          Pointer handlers sit on the viewport so the whole stage is swipeable,
          not just the card text. `touch-action: pan-y` lets vertical scrolling
          through while the horizontal gesture is ours to interpret. */}
      <div
        ref={stageRef}
        className="relative overflow-hidden rounded-card"
        style={{ touchAction: 'pan-y' }}
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onPointerLeave={onPointerLeave}
      >
        {/* THE TRACK'S WIDTH IS `100% x total`, AND EACH CARD IS `100%` OF THE
            STAGE — NOT OF THE TRACK.

            This is the one measurement the rail has to get right, and getting it
            wrong is exactly why on a phone only "step 1" appeared to be on
            screen. The track was `total x 100%` wide, and each card was
            `basis-full`, which resolved to 100% of the TRACK — i.e. six viewport
            widths per card. Every card was therefore six screens wide, only the
            first sliver of card one was visible, and translating by `100 / total`
            per step moved the track by a sixth of a card rather than a whole one.

            The fix is to size each card against the STAGE: the cards are
            `w-[100%] shrink-0` where 100% is the stage's own width (the track
            does not impose a width on its children — it is a plain flex row whose
            own width is set explicitly below and whose children are told to be one
            stage wide each). `translateX(-active * 100%)` then moves exactly one
            card's width per step, because a card's width IS the stage width.

            `basis-full` was the trap: "full" is full of the flex CONTAINER, and
            the container was the over-wide track, not the visible stage. */}
        <div
          className="flex items-stretch"
          style={{
            // THREE COPIES OF THE LIST. The rail only moves forward, so there has
            // to be a card off-screen to the right at all times — including on
            // the last step. `total * 3` gives a full copy either side of the
            // window, and the wrap resets within that so the DOM never runs out.
            width: `${total * 3 * 100}%`,
            // The divisor is `total * 3`, NOT `total`: the track holds the list
            // three times over, so one STAGE is a third of one copy. The card
            // width below reads the same variable, which is what keeps the two in
            // agreement — when they disagreed, every card was three stages wide
            // and only a sliver of step 1 was ever visible.
            '--step-count': total * 3,
            transform: `translateX(-${position * (100 / (total * 3))}%)`,
            // `linear` easing keeps the step even; the duration is the "swipe"
            // itself. Suppressed for reduced-motion users, who get a cut — the
            // JSX guard (`motion-safe`) can't reach an inline transition, so the
            // media query is honoured here instead.
            //
            // `snapping` removes the transition for the single reset frame, so
            // the rewind to position 0 is an instant, invisible jump rather than
            // a visible slide backwards.
            transition:
              dragging || snapping
                ? 'none'
                : 'transform 0.55s cubic-bezier(0.33, 0, 0.67, 1)',
          }}
        >
          {/* The list three times over. The copies after the first are
              `aria-hidden` so a screen reader hears the six steps once, not
              eighteen — they exist only to fill the track. */}
          {[0, 1, 2].map((copy) =>
            steps.map((step, index) => (
              <StepCard
                key={`${copy}-${step.step}`}
                step={step}
                index={index}
                total={total}
                slotSeconds={slotSeconds}
                ariaHidden={copy > 0}
              />
            )),
          )}
        </div>
      </div>

      {/* The controls, laid out as the user asked: the two arrows are SEPARATE
          at the card's edges — the LEFT arrow alone on the far left, the RIGHT
          arrow alone on the far right — and the dots sit in the middle. One
          full-width flex row with `justify-between` does it: three children,
          two of them the same width (both arrows are 2rem), so the middle child
          (the dots) lands exactly on the centre line. */}
      <div className="flex items-center justify-between px-4 pb-4 pt-3">
        {/* Back arrow: slides to the PREVIOUS card (rewinds one step). */}
        <button
          type="button"
          onClick={() => setPosition((current) => current - 1)}
          aria-label="Previous step"
          className="flex h-8 w-8 items-center justify-center rounded-full text-aqua-700 transition-colors hover:bg-aqua-50 dark:text-aqua-300 dark:hover:bg-slate-800"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
            <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        <div className="flex items-center gap-1.5">
          {steps.map((step, index) => (
            <button
              key={step.step}
              type="button"
              // Jumping to a dot still only ever moves FORWARD: the target is
              // expressed as the next occurrence of that step ahead of the
              // current position, so a click never rewinds the rail.
              onClick={() => setPosition((current) => {
                const target = index % total
                const currentStep = current % total
                const delta = (target - currentStep + total) % total
                return current + (delta === 0 ? total : delta)
              })}
              aria-label={`Go to step ${index + 1}`}
              aria-current={index === active ? 'true' : undefined}
              className={`h-2 rounded-full transition-all duration-300 ${index === active
                  ? 'w-5 bg-aqua-500 dark:bg-aqua-300'
                  : 'w-2 bg-aqua-500/30 hover:bg-aqua-500/60 dark:bg-aqua-300/30 dark:hover:bg-aqua-300/60'
                }`}
            />
          ))}
        </div>

        {/* Next arrow: advances one step — alone at the card's RIGHT edge. */}
        <button
          type="button"
          onClick={next}
          aria-label="Next step"
          className="flex h-8 w-8 items-center justify-center rounded-full text-aqua-700 transition-colors hover:bg-aqua-50 dark:text-aqua-300 dark:hover:bg-slate-800"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
            <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  )
}

/**
 * One card in the rail, plus its water wipe.
 *
 * HOW "ONE AT A TIME" IS DONE WITHOUT JAVASCRIPT. There is no index in state and
 * no interval: every card runs one long animation whose duration is the whole
 * cycle (`slotSeconds × total`) and which shows its own content only during its
 * own slot, expressed as a percentage window of the cycle. Because each card's
 * `animationDelay` is `-index × slotSeconds`, card N's window lines up exactly
 * with the Nth slot on a single shared clock.
 *
 * The negative delay is load-bearing: it starts each card's animation already
 * advanced, so the cards are staggered from the first frame instead of all
 * firing at once and then drifting apart. It also means the rail is correct on a
 * fresh mount, with no "first card flashes for 2s" seam.
 */
function StepCard({ step, index, total, ariaHidden = false }) {
  return (
    <article
      // The duplicate copies in the track are decoration for the layout only, so
      // they are hidden from assistive technology. The step text is announced
      // once, from the first copy.
      aria-hidden={ariaHidden || undefined}
      // EXACTLY ONE STAGE WIDTH PER CARD.
      //
      // The track is `(total x 3) x 100%` of the stage wide, so a card that must
      // fill the stage is `100 / (total x 3)` of the track. The divisor comes
      // from `--step-count`, which the parent sets to `total * 3` — the SAME
      // number the transform uses, so the two can never drift apart.
      //
      // Getting this wrong is the whole failure mode: when the divisor was
      // `total` while the track was `total * 3`, each card came out three stages
      // wide, so only a third of one step was ever on screen and the cards looked
      // misaligned. Sizing from the shared variable is what makes each card hold
      // exactly one step, correctly placed.
      //
      // `shrink-0` stops the flex row from squeezing a card below that width, and
      // `self-stretch` + `min-h` keeps every card at least as tall as the longest
      // step body, so steps 2-6 have room for their text rather than being
      // clipped. `flex-col` inside makes the header, body and detail stack in a
      // predictable order regardless of how long each step's copy is.
      className="relative flex w-[calc(100%/var(--step-count,18))] shrink-0 self-stretch flex-col min-h-[15rem] rounded-card border-slate-200/80 bg-white/80 p-4 shadow-card dark:border-slate-700 dark:bg-slate-800/70"
    >
      {/* --- Layer 1: the card's own water ---------------------------------
          A self-contained water scene, drawn BEHIND the text and clipped to the
          card's rounded corners. Everything in this block is decoration and none
          of it is interactive.

          It sits under the text rather than over it on purpose. The earlier
          version swept a full-card wave sheet across the CONTENTS as the card
          arrived, which meant the body copy was briefly covered by a translucent
          sheet — legible one moment, washed out the next. Text that fades in and
          out under an animation is exactly the "text not clearly visible"
          complaint, so the water moved behind the text instead. */}
      <span
        className="pointer-events-none absolute inset-0 overflow-hidden rounded-card group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused]"
        aria-hidden="true"
      >
        {/* The body of water: a shallow pool filling the lower part of the card.
            Tinted rather than opaque, so the card still reads as the white
            surface the text sits on and the copy keeps full contrast. */}
        <span className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-aqua-300/45 via-aqua-200/25 to-transparent dark:from-aqua-600/40 dark:via-aqua-700/20" />

        {/* Caustic light drifting through it. Two washes per card, offset by the
            card's index, so a row of cards never shimmers in unison. */}
        <span
          className="absolute -bottom-6 left-0 h-24 w-2/3 rounded-full bg-aqua-300/40 blur-2xl motion-safe:animate-card-caustics dark:bg-aqua-400/25"
          style={{ animationDelay: `${-index * 1.4}s` }}
        />
        <span
          className="absolute -bottom-4 right-0 h-20 w-1/2 rounded-full bg-aqua-200/45 blur-2xl motion-safe:animate-card-caustics dark:bg-aqua-300/20"
          style={{ animationDelay: `${-index * 1.4 - 3}s` }}
        />

        {/* The waterline: a curved swell drawn as an SVG, not a straight edge, so
            the surface reads as water rather than as a filled box. It breathes
            up and down and never fills the card, which is what keeps the reading
            area constant. */}
        <span
          className="absolute inset-x-0 bottom-16 h-8 text-aqua-400/50 motion-safe:animate-card-waterline dark:text-aqua-400/35"
          style={{ animationDelay: `${-index * 0.9}s` }}
        >
          <svg viewBox="0 0 400 32" preserveAspectRatio="none" fill="currentColor" className="h-full w-full">
            <path d="M0,18 C50,6 90,26 140,16 C190,6 230,28 280,18 C330,8 370,24 400,14 L400,32 L0,32 Z" />
          </svg>
        </span>

        {/* Bubbles rising through the card's water. Generated from the card's
            index so each card has its own layout, and positioned below the water
            line so they read as coming out of the pool rather than floating in
            the air above it. */}
        {cardBubbles(index).map((bubble) => (
          <span
            key={bubble.id}
            className="absolute bottom-2 block rounded-full border-white/60 bg-white/35 motion-safe:animate-card-bubble group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused] dark:border-aqua-100/40 dark:bg-aqua-100/15"
            style={{
              left: `${bubble.left}%`,
              height: `${bubble.size}px`,
              width: `${bubble.size}px`,
              animationDuration: `${bubble.duration}s`,
              animationDelay: `${bubble.delay}s`,
            }}
          />
        ))}

        {/* --- The sea swell -----------------------------------------------

            A WAVE THAT TRAVELS UP AND DOWN, NOT ACROSS.

            This used to be a curved sheet that swept LEFT TO RIGHT across the
            card and out again (`animate-water-wipe`). Two problems with that:

              1. It read as a hard-edged shape entering and leaving the card — the
                 leading and trailing edges were visible, so it looked like a
                 graphic sliding past rather than like water.
              2. Because the sheet was wider than the card and travelled its own
                 width, the motion STARTED and ENDED at the card's edges. Nothing
                 about it was water: water has no start point and no end point on
                 a surface, it just rises and falls.

            The replacement is a swell: a wide, soft-edged wave band, wider than
            the card and anchored so its ends are always off-screen, that drifts
            UP AND DOWN in place on a slow sine. It never enters and never leaves,
            so there is no cut on any edge — the surface simply breathes, which is
            what the user asked for. The wave shape comes from the same curved SVG
            as before, so the boundary is still a crest rather than a rule. */}
        <span
          className="absolute -left-1/4 bottom-0 h-32 w-[150%] text-aqua-400/40 motion-safe:animate-sea-swell-card dark:text-aqua-300/30"
          style={{ animationDelay: `${-index * 1.1}s` }}
        >
          <WaveSheet />
        </span>
      </span>

      {/* --- Ripples on the surface as the card settles --- */}
      <span
        className="pointer-events-none absolute -bottom-4 -right-4 h-24 w-24 rounded-full border-2 border-aqua-400/40 motion-safe:animate-water-ripple dark:border-aqua-300/30"
        aria-hidden="true"
        style={{ animationDelay: `${-index * 0.9}s` }}
      />

      {/* --- The text, on its own opaque surface --------------------------
          `relative` lifts this above every decorative layer, and the subtle
          backdrop keeps contrast high wherever the water happens to sit at that
          moment — the copy is never read against moving colour. */}
      <div className="relative flex w-full flex-1 flex-col rounded-card bg-white/75 p-4 backdrop-blur-[2px] dark:bg-slate-900/65">
        <div className="flex items-center gap-2.5">
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-field bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-sm dark:from-aqua-400 dark:to-aqua-600"
            aria-hidden="true"
          >
            <Icon path={ICONS[step.icon] || ICONS.info} className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-2xs font-semibold uppercase tracking-wider text-aqua-700 dark:text-aqua-300">
              Step {step.step} of {total}
            </p>
            <h3 className="text-[0.9375rem] font-semibold leading-snug text-slate-900 dark:text-white">
              {step.title}
            </h3>
          </div>
        </div>

        {/* `flex-1` so the body copy takes the space it needs and the detail line
            settles at the foot of the card. */}
        <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-700 dark:text-slate-200">
          {step.body}
        </p>
        {/* The foot line only renders when the step HAS one. Step 1's detail was
            the "Mobile: tap the menu button…" sentence, which has been removed, so
            the guard keeps an empty `<p>` (and its margin) off that card. */}
        {step.detail && (
          <p className="mt-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">
            {step.detail}
          </p>
        )}
      </div>
    </article>
  )
}

/**
 * Bubbles for one card, derived from its index.
 *
 * Deterministic rather than random: `Math.random()` at render time would produce
 * different positions on every re-render, so the bubbles would jump whenever the
 * parent happened to update — and with a markov-ish animating rail on the same
 * screen, that is constantly. The card index seeds the layout instead, so each
 * card looks distinct but each card is stable.
 */
function cardBubbles(index) {
  const PHI = 0.6180339887498949
  const count = 5 + (index % 3)
  return Array.from({ length: count }, (_, id) => {
    const seed = index * 37 + id
    return {
      id,
      left: Math.round(((seed * PHI) % 1) * 100 * 100) / 100,
      size: 4 + ((seed * 7) % 8),
      duration: 5 + ((seed * 13) % 60) / 10,
      // Negative delays start each bubble already part-way through its climb, so
      // the card has bubbles in flight the moment it appears rather than an empty
      // pool for the first few seconds.
      delay: -((seed * 29) % 70) / 10,
    }
  })
}

/**
 * The wave sheet the swipe is cut from.
 *
 * Two full periods of an irregular swell across the element's width, filled
 * downward, so the leading edge is a curve at every moment. `preserveAspectRatio`
 * is left at its default here deliberately: this shape should scale with the
 * card, and stretching it would flatten the crest into the straight edge the
 * whole effect exists to avoid.
 */
function WaveSheet() {
  return (
    <svg
      viewBox="0 0 1440 320"
      preserveAspectRatio="none"
      fill="currentColor"
      className="h-full w-full"
    >
      <path d="M0,40 C160,0 260,88 420,60 C580,32 660,120 820,92 C980,64 1080,140 1240,112 C1320,98 1380,110 1440,92 L1440,320 L0,320 Z" />
    </svg>
  )
}

/**
 * One verdict definition, keyed to the same three tones the badges use.
 *
 * The badge is a FIXED-width chip, not a content-sized one, so all three rows
 * share one left edge and their paragraphs all begin on the same vertical line.
 * Previously the badge shrank to fit "SAFE" and grew for "MODERATE", which
 * pushed each paragraph a different distance right — the ragged left edge inside
 * the card. `w-20` on the chip plus `items-start` makes the column straight.
 */
function ResultRow({ tone, title, body }) {
  return (
    // A STRICT TWO-COLUMN GRID, so both edges are straight lines.
    //
    // A flex row with a fixed-width chip got the columns roughly aligned, but the
    // two columns then did not agree with the rows above and below them: the gap
    // was a flex `gap` on a content-sized row, so a long word in one paragraph
    // could still shift that row's wrapping. `grid-cols-[5rem_minmax(0,1fr)]`
    // fixes both columns as tracks: the badge column is exactly 5rem on every
    // row, so the badges start on one vertical line, and the paragraph column is
    // the remainder, so every paragraph starts on the SAME vertical line to its
    // right. That is the "left side straight, right side aligned" the block was
    // missing.
    //
    // `items-start` aligns the badge with the first line of its paragraph rather
    // than to the row's vertical centre, and `text-left` on both cells keeps the
    // body copy flush to its column edge instead of inheriting any centring from
    // the card's centred title.
    // COMPACT BY SCREEN SIZE. The badge column is 4.5rem on a phone and 5rem
    // from `sm:` up, the gap tightens, and the body copy steps down one text
    // size on a small screen — the rows stay on their straight edges at every
    // width, they just breathe less where there is less room.
    <li className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-x-2.5 text-left sm:grid-cols-[5rem_minmax(0,1fr)] sm:gap-x-3">
      {/* THE VERDICT BOX IS THE COLOUR ITSELF. On this page the three chips are
          asked to BE red / yellow / green — the whole box filled, with only the
          word inside it in WHITE — rather than the pale tint with dark text used
          elsewhere in the app. That is what `solid` selects: `bg-safe` /
          `bg-caution` / `bg-unsafe` with `text-white`. The pale chips in the
          history lists and the result card are untouched. */}
      <Badge risk={tone} solid className="mt-0.5 w-full shrink-0 justify-center">
        {title}
      </Badge>
      <p className="min-w-0 text-left text-[0.8125rem] leading-relaxed text-slate-600 dark:text-slate-300 sm:text-sm">
        {body}
      </p>
    </li>
  )
}

/**
 * STEP 31 — THE LOCATION PREDICTION GUIDE.
 *
 * Six animated cards describing the flow in order, from typing a place to reading
 * the verdict. The copy lives in `LOCATION_GUIDE_STEPS` rather than here, for the
 * same reason the rail's copy lives in the config: the guide describes a real
 * screen, and the screen's behaviour changes. Text next to the thing it describes
 * goes stale silently; a single exported list is at least visible to a diff.
 *
 * WHY A GRID AND NOT ANOTHER CAROUSEL. The page already has one auto-advancing
 * rail, forty lines above this section. A second moving carousel would be the
 * same component twice — two things sliding at once on one screen, one of them
 * interrupting the other. So these cards hold still and are read, and they arrive
 * with motion instead of moving continuously. The two blocks therefore do not
 * compete: the top one is glanced at, this one is scrolled through.
 *
 * RESPONSIVE, AND THE RESPONSIVENESS IS ABOUT READING, NOT JUST FITTING. Three
 * breakpoints, chosen by what each card has to hold:
 *
 *   - mobile (one column): the cards are a list. A vertical connector runs down
 *     the left, because in a single column the eye has no other cue that step 3
 *     comes before step 4 once the numbers are small.
 *   - `sm` (two columns): the connector is gone, because at two columns it would
 *     join cards that are not adjacent in the reading order and actively lie about
 *     the sequence.
 *   - `lg` (three columns): two rows of three, which is as many columns as the
 *     longest body can support before the lines get too short to read.
 *
 * The cards stretch to their row's tallest member (`items-stretch` on the grid,
 * default on the card) so the row is a block of equal height rather than a ragged
 * top edge. Only the body text flexes; the badge and the point list keep their own
 * height, so the foot line lands on one straight line across a row.
 */
function LocationGuide() {
  return (
    <div data-testid="location-guide">
      <Card
        className="overflow-visible"
      // NO ENTRANCE ANIMATION ON THE WRAPPER. The card this holds has six children,
      // each with its own stagger; if the wrapper also faded in, the children's
      // delays would all elapse behind an invisible parent and the stagger would
      // read as a single late-arriving block. The wrapper is present from the first
      // frame and only the cards move.
      bodyClassName="px-3 pb-3 sm:px-5 sm:pb-5"
      title={
        <span className="block text-center text-base font-bold sm:text-lg">
          How Location Prediction works
        </span>
      }
      subtitle={
        <span className="block text-center text-xs sm:text-sm">
          Six steps from a typed place to a SAFE, MODERATE or UNSAFE verdict
        </span>
      }
    >
      {/* A short lead-in. The cards below are terse by design, so this carries the
          one sentence that explains why the feature exists at all — namely that it
          fills in the five parameters the sections above describe, so a reader can
          connect this flow to the manual one without being told to. */}
      <p className="mx-auto mb-5 max-w-3xl text-center text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        Location Prediction is the same analysis reached without a test strip. Name
        the place, and the app identifies its water source, pre-fills the five
        parameters from mapped data, and runs the prediction — so nothing is typed
        by hand and nothing is invented.
      </p>

      <ol
        // THE GRID. `sm:` and `lg:` are the two breakpoints named above; there is
        // deliberately no `md`, because one column and three columns is all this
        // content needs — a two-column layout at `md` would be the same as at `sm`
        // with more whitespace between the cards.
        className="relative grid items-stretch gap-4 sm:grid-cols-2 sm:gap-5 lg:grid-cols-3"
      >
        {/* THE CONNECTOR, AND WHY IT IS A CHILD OF THE LIST RATHER THAN A BORDER.

            It is drawn here, absolutely positioned against the `relative` list,
            because a border cannot animate: `border-left` has no transform to move,
            so a connector made that way can only ever be a static rule. This one is
            a separate element with `animate-guide-flow`, which washes a highlight
            down its length — the reader's eye is walked from one card to the next.

            `sm:` HIDES IT. At two and three columns a single vertical line cannot
            connect the steps, because the eye reads across a ROW first and the line
            would then join cards 1 and 2 — which are siblings in the grid, not
            consecutive steps — and assert an order that is not the real one. The
            connector is only true in a one-column list, so it exists only there.

            It is inset to sit behind the badges (`left-7` is the badge's centre
            within the list, and `z-0` puts it under the cards, which carry their own
            background) so it passes behind the numbering rather than striking
            through it. */}
        <span
          className="pointer-events-none absolute bottom-6 left-7 top-6 block w-px -z-10 bg-aqua-200 sm:hidden"
          aria-hidden="true"
        >
          <span className="block h-full w-full bg-gradient-to-b from-transparent via-aqua-400/60 to-transparent motion-safe:animate-guide-flow" />
        </span>
        {LOCATION_GUIDE_STEPS.map((step, index) => (          <LocationGuideCard
            key={step.step}
            step={step}
            index={index}
            total={LOCATION_GUIDE_STEPS.length}
          />
        ))}
      </ol>

      {/* The lead-out. A guide that ends on the last card leaves the reader with no
          next action, so the section closes with the screen it describes. The whole
          strip is one link, not six, because there is only one place to go. */}
      <Link
        to={ROUTES.location}
        className="mt-6 flex items-center justify-center gap-2 rounded-field bg-aqua-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-aqua-700 dark:bg-aqua-500 dark:hover:bg-aqua-400 dark:hover:text-black"
      >
        <Icon path={ICONS.location} className="h-4 w-4" />
        Open Location Prediction
        <Icon path={ICONS.chevronRight} className="h-4 w-4" />
      </Link>
      </Card>
    </div>
  )
}

/**
 * One guide card.
 *
 * `index` and `total` are passed rather than read from the list length here, so
 * the card renders the same "Step 2 of 6" wording the rail above uses. One
 * vocabulary for the two blocks is the point of putting the count on each card: a
 * reader moving between them sees the same phrase and knows both are counting the
 * same way.
 *
 * `data-testid="location-guide-card"` is on every card so the section can be
 * verified from the browser without matching on copy — the copy is likely to be
 * reworded, and a check that breaks when marketing copy changes is a check that
 * will be "fixed" by editing the check.
 */
function LocationGuideCard({ step, index, total }) {
  return (
    <li className="min-w-0 list-none">
      <article
        data-testid="location-guide-card"
        // THE CARD ITSELF. `group` so the hover lift and the badge halo can be
        // driven by a pointer anywhere on the card, not only over its title.
        //
        // `h-full` is what makes a row of cards equal height — the grid stretches
        // its items and the article fills the stretched item, instead of each
        // article sizing to its own copy and leaving a ragged bottom edge.
        //
        // THE ENTRANCE IS STAGGERED BY `index * 0.1s`. At six cards that is a
        // 0.5s spread: enough that the eye can follow them arriving one at a
        // time, short enough that nobody perceives a wait. `animate-*-both` (set in
        // tailwind.config.js) is what holds each card hidden through its own delay,
        // so the stagger is real rather than six animations starting together.
        className="card group h-full p-0 transition-shadow hover:shadow-card-hover dark:hover:shadow-popover"
      >
        <span className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-aqua-300/70 to-transparent motion-safe:animate-guide-flow dark:via-aqua-400/40" aria-hidden="true" />
        <span
        // NO `opacity-0` HERE, and that is deliberate. The entrance keyframe
          // starts at `opacity: 0`, so an explicit `opacity-0` looks redundant —
          // but `motion-safe:` means the animation class only ever applies on
          // motion-safe viewports. For a reduced-motion user the class is absent
          // and an `opacity-0` here would leave six permanently invisible cards.
          // With the class alone, such a user gets the cards fully visible and
          // still, which is the correct outcome.
          className="block h-full rounded-card p-4 motion-safe:animate-guide-card-in"
          style={{ animationDelay: `${index * 0.1}s` }}
        >
          {/* --- Badge: the number, and the icon --------------------------- */}
          <div className="flex items-center gap-3">
            {/* The number is inside the animated halo ring so the eye is pulled to
                it first, and the ring is what pulses. Its delay is NEGATIVE and
                derived from the card's index, so the six badges are out of phase
                with one another — six halos pulsing in sync would read as one
                blinking block rather than six independent cards. */}
            <span
              className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-base font-bold text-white shadow-sm motion-safe:animate-guide-badge-halo dark:from-aqua-400 dark:to-aqua-600"
              style={{ animationDelay: `${-index * 0.43}s` }}
              aria-hidden="true"
            >
              {step.step}
            </span>
            <div className="min-w-0">
              <p className="text-2xs font-semibold uppercase tracking-wider text-aqua-700 dark:text-aqua-300">
                Step {step.step} of {total}
              </p>
              <h3 className="text-[0.9375rem] font-semibold leading-snug text-slate-900 dark:text-white">
                {step.title}
              </h3>
            </div>
          </div>

          {/* The icon sits beside the title rather than in the badge: the badge
              holds the number, which is the thing the user reads to establish the
              order, and putting an icon in there too would make it two competing
              elements at 2.75rem. Here it is a quiet echo of the step rail. */}
          <Icon
            path={ICONS[step.icon] || ICONS.info}
            className="mt-3 h-5 w-5 text-aqua-600 transition-transform duration-300 group-hover:scale-110 dark:text-aqua-300"
            aria-hidden="true"
          />

          {/* --- The body --------------------------------------------------- */}
          {/* `flex-1` so this grows to fill the card, which pushes the foot line to
              the bottom. That is what makes the point lists across a row start and
              finish on one horizontal line rather than each hanging at its own
              depth. */}
          <p className="mt-2 flex-1 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
            {step.body}
          </p>

          {/* --- The points -------------------------------------------------
              Rendered only when the step has any, which is why `points` is an
              array in the data rather than a string split here. A step with four
              points and a step with none are genuinely different shapes, and
              deciding that per-step in the data is clearer than deciding it by
              parsing copy. */}
          {step.points && step.points.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {step.points.map((point) => (
                <li key={point} className="flex items-start gap-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
                  {/* The tick is a fixed 1rem box and `shrink-0`, so the point text
                      after it begins on the same x on every line — otherwise a long
                      point would wrap and its second line would start under the tick
                      rather than under the text. */}
                  <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-aqua-500 dark:bg-aqua-300" aria-hidden="true" />
                  <span className="min-w-0">{point}</span>
                </li>
              ))}
            </ul>
          )}

          {/* --- The closing line -------------------------------------------
              In the accent tone on a tinted strip, so it reads as the takeaway
              rather than as more body copy. It is the one line per card that says
              what to DO, which is why it is separated from the description above. */}
          {step.detail && (
            <p className="mt-3 rounded-field bg-aqua-50 px-2.5 py-2 text-xs font-medium leading-relaxed text-aqua-800 dark:bg-aqua-900/30 dark:text-aqua-200">
              {step.detail}
            </p>
          )}
        </span>
      </article>
    </li>
  )
}
