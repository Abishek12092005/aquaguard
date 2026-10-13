/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  // Tailwind only emits a keyframe when some utility class references it, and it
  // learns that by SCANNING FILES for class names. The Home rail needs `show-six`
  // with a per-card duration and delay, so it sets `animationName` as an inline
  // style — an inline string is invisible to the scanner, so the keyframe was
  // compiled away and the rail silently did nothing. Naming the utility here is
  // what keeps the keyframe in the output while the component controls timing.
  //
  // The three `badge-solid-*` classes are built at runtime by `Badge` from
  // `riskTone()` (the literal string is assembled with `replace`, not written
  // out), so Tailwind's scanner never sees it and would compile the rule away.
  // They are the Home page's filled verdict boxes, so they are listed here to
  // guarantee the CSS is emitted.
  safelist: [
    'animate-show-six',
    'badge-solid-safe',
    'badge-solid-moderate',
    'badge-solid-unsafe',
  ],
  // Dark mode is driven by a `dark` class on <html>, toggled by ThemeContext and
  // persisted in localStorage — not by `prefers-color-scheme` alone. The OS
  // preference is read once as the *initial* value, but the user's explicit
  // choice has to win: someone on a dark-set machine still needs to be able to
  // pick light, and `media` mode would ignore that entirely.
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // AquaGuard palette — a single source of truth for the water theme,
        // exposed as Tailwind utilities (bg-aqua-500, text-safe, etc.).
        aqua: {
          50: '#eff9ff',
          100: '#dcf1ff',
          200: '#b8e4ff',
          300: '#7ed1ff',
          400: '#3bb8ff',
          500: '#0e9de8',
          600: '#007cc6',
          700: '#0163a0',
          800: '#065384',
          900: '#0b466e',
          950: '#072c49',
        },
        safe: {
          light: '#dcfce7',
          DEFAULT: '#16a34a',
          dark: '#15803d',
        },
        caution: {
          light: '#fef3c7',
          DEFAULT: '#d97706',
          dark: '#b45309',
        },
        unsafe: {
          light: '#fee2e2',
          DEFAULT: '#dc2626',
          dark: '#b91c1c',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      // One radius scale, used everywhere. "card" is the default surface radius
      // and "field" the control radius, so inputs and buttons line up with the
      // cards they sit in rather than each inventing its own rounding.
      borderRadius: {
        field: '0.625rem', // 10px - inputs, buttons, small controls
        card: '0.875rem', // 14px - cards, panels
        panel: '1.125rem', // 18px - large surfaces (chat panel, dialogs)
      },
      // A three-step elevation ramp. Cards rest, hover lifts slightly, and only
      // genuinely floating surfaces (menus, the assistant panel) go higher.
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        'card-hover':
          '0 4px 6px -1px rgb(15 23 42 / 0.07), 0 2px 4px -2px rgb(15 23 42 / 0.05)',
        popover: '0 10px 24px -6px rgb(15 23 42 / 0.16), 0 4px 8px -4px rgb(15 23 42 / 0.08)',
        panel: '0 20px 50px -12px rgb(15 23 42 / 0.30)',
      },
      // Extra-small text step for dense metadata (badges, table meta, timestamps)
      // so those stay consistent instead of being hand-written as text-[10px].
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }], // 11px
      },
      spacing: {
        // Section rhythm: the gap between major page blocks.
        section: '1.5rem',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // --- Water loader (sea) -------------------------------------------
        // Rain falling the full height of the viewport, top to surface. Distinct
        // from `rain-fall` (which uses vh units for the app backdrop) because
        // the loader is `fixed inset-0` and needs to land exactly on the sea.
        'rain-fill': {
          '0%': { transform: 'translate3d(0, -10%, 0)', opacity: '0' },
          '12%': { opacity: '1' },
          '100%': { transform: 'translate3d(0, 78vh, 0)', opacity: '0' },
        },
        // The sea, rising in waves.
        //
        // The old keyframe scaled a flat band on Y, and the band had a drawn
        // waterline plus a pair of counter-scrolling wave SVGs sitting ON its
        // top edge — which meant the surface was a straight horizontal rule
        // sliding up the screen. A straight rule is a progress bar; it is not
        // water.
        //
        // So the rise is now driven by clip-path instead of scaleY. The wave
        // crest is part of the clipped shape: the fill boundary is a genuinely
        // slanted curve at every frame, because the sea (waves and all) is
        // already laid out to the full height and we only reveal the part below
        // the surface. Nothing about the shape is drawn on top of anything, so
        // there is no line to see — the edge IS the water.
        //
        // The end value (55%) is read back by every wave layer through its own
        // `bottom: 55%`, so the crests, the foam and the swells all agree on
        // where the surface is at that moment, and all of them ride up together
        // instead of the water sliding out from under a fixed decoration.
        //
        // One 3s cycle: flood up, hold a beat, recede to a thin film at the
        // bottom (18%, not 0 — a sea that vanished completely each loop would
        // expose the ground and read as a reset rather than a tide).
        // WHY A POLYGON AND NOT AN `inset()`. `clip-path: inset()` is a rectangle:
        // its top edge is a perfectly straight horizontal rule, and interpolating
        // between two insets gives a straight rule that slides — the exact
        // artefact this rewrite exists to remove. A `polygon()` can carry the
        // wave: the top points are placed at different heights, so the fill
        // boundary is a curve AT EVERY FRAME, including the interpolated ones.
        //
        // Reading the polygon: `x y` pairs across the block, then the two bottom
        // corners to close the shape. The y values are percentages of the SEA
        // BLOCK's height, so 100% is the very bottom of the block (hidden) and
        // 0% is its top edge — the waterline the crest stops at.
        //
        // HOW CURVED, AND WHY IT NEEDED BOTH KEYS. A seven-point profile only
        // moves the boundary a few percent per keyframe, which at 45% of a
        // viewport is a shallow, almost-flat undulation — and because the profile
        // is carried up UNCHANGED, the curve was the same curve at every moment.
        // The result read as a gently-bowed edge, not as a wave.
        //
        // Two changes fix that:
        //
        //   1. THIRTEEN top points instead of seven, with a much wider amplitude
        //      (a swing of roughly 18% of the block between crest and trough).
        //      More points is what makes the edge read as a wave rather than as a
        //      shallow arc; the amplitude is what makes it visible at all.
        //
        //   2. The profile is now RESHAPED between keyframes rather than only
        //      lifted. The crests travel LEFT-TO-RIGHT as the water climbs — the
        //      heights move across the row of points, so the same water reads as
        //      a wave in motion instead of a rigid shape being raised.
        //
        // The phase alternates per keyframe on purpose: a wave that kept sliding
        // one way would look like the water was being dragged sideways. Swapping
        // direction each step reads as swell, which is what water does.
        'sea-rise': {
          // Hidden: every point at the block's bottom edge, so there is no
          // visible curve to jump from when the cycle starts.
          '0%': {
            'clip-path':
              'polygon(0% 100%, 8.3% 100%, 16.6% 100%, 25% 100%, 33.3% 100%, 41.6% 100%, 50% 100%, 58.3% 100%, 66.6% 100%, 75% 100%, 83.3% 100%, 91.6% 100%, 100% 100%, 100% 100%, 0% 100%)',
          },
          // Rising, first phase: crests sit left of centre.
          '22%': {
            'clip-path':
              'polygon(0% 62%, 8.3% 50%, 16.6% 58%, 25% 44%, 33.3% 55%, 41.6% 47%, 50% 60%, 58.3% 49%, 66.6% 57%, 75% 45%, 83.3% 56%, 91.6% 48%, 100% 58%, 100% 100%, 0% 100%)',
          },
          // Second phase: the crests have travelled right, and the amplitude
          // opens up as the water gains height.
          '42%': {
            'clip-path':
              'polygon(0% 30%, 8.3% 20%, 16.6% 33%, 25% 12%, 33.3% 26%, 41.6% 14%, 50% 29%, 58.3% 16%, 66.6% 31%, 75% 11%, 83.3% 27%, 91.6% 18%, 100% 28%, 100% 100%, 0% 100%)',
          },
          // Arrived, at full height. This is the frame the label sits against,
          // and the wave is at its deepest here so the surface is unmistakably a
          // curve at the moment the user is looking at it.
          '58%': {
            'clip-path':
              'polygon(0% 7%, 8.3% 0%, 16.6% 9%, 25% 2%, 33.3% 4%, 41.6% 22%, 50% 17%, 58.3% 21%, 66.6% 3%, 75% 6%, 83.3% 9%, 91.6% 1%, 100% 8%, 100% 100%, 0% 100%)',
          },
          // Held, but the wave keeps travelling — the water is still moving even
          // while the level is not, which is what stops the hold looking frozen.
          '76%': {
            'clip-path':
              'polygon(0% 8%, 8.3% 1%, 16.6% 4%, 25% 2%, 33.3% 9%, 41.6% 22%, 50% 3%, 58.3% 6%, 66.6% 21%, 75% 17%, 83.3% 3%, 91.6% 4%, 100% 9%, 100% 100%, 0% 100%)',
          },
          // Recedes to a film, not to nothing: the trough sits around 78% of a
          // 45%-tall block, so water is always on screen. A sea that vanished
          // completely each loop exposed the seabed for a frame and read as a
          // reset rather than as a tide.
          '100%': {
            'clip-path':
              'polygon(0% 78%, 8.3% 70%, 16.6% 79%, 25% 66%, 33.3% 76%, 41.6% 62%, 50% 74%, 58.3% 68%, 66.6% 77%, 75% 65%, 83.3% 75%, 91.6% 69%, 100% 76%, 100% 100%, 0% 100%)',
          },
        },
        // A second, decoupled wave that rides just above the fill edge, so the
        // boundary the user sees is two curves crossing rather than one.
        //
        // This is the layer that makes the surface read as WATER rather than as a
        // single smoothly-animated shape: a real waterline is never one clean
        // sine, it is several overlapping ones. It animates on its own duration
        // (7s against the fill's 3s) so the two never settle into a repeating
        // pattern the eye can lock onto.
        'sea-surface-drift': {
          '0%': { transform: 'translate3d(-4%, 0, 0)' },
          '50%': { transform: 'translate3d(4%, -6px, 0)' },
          '100%': { transform: 'translate3d(-4%, 0, 0)' },
        },
        // Foam riding the crest: fades in as the sea arrives, thins as it
        // settles, comes back with the next wave. Opacity only, so it costs
        // nothing.
        'sea-foam': {
          '0%, 18%': { opacity: '0' },
          '34%': { opacity: '0.9' },
          '76%': { opacity: '0.55' },
          '100%': { opacity: '0.25' },
        },
        // A crest bobbing on the surface — the lowest-frequency motion, so the
        // sea breathes rather than only translating.
        'sea-bob': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0)' },
          '50%': { transform: 'translate3d(0, -0.5rem, 0)' },
        },
        // The caustic light under the surface swimming around. Slow, and
        // deliberately out of phase with everything else so the loop seam does
        // not line up.
        'sea-caustics': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)', opacity: '0.55' },
          '50%': { transform: 'translate3d(-3%, -2%, 0) scale(1.15)', opacity: '0.8' },
        },
        // (`sea-swell` — a scrolling crest band — used to live here. The loader's
        // surface is now the edge of the `sea-rise` polygon, so a band that
        // scrolled horizontally had nothing to define and was removed with the
        // WaveField helper it drove.)

        // Droplets in the air above the surface: fling out of the sea, hang,
        // fall back into it. Starts and ends below the surface so a droplet is
        // never seen being born or destroyed.
        'sea-spray': {
          '0%': { transform: 'translate3d(0, 0, 0) scale(0.5)', opacity: '0' },
          '15%': { opacity: '0.9' },
          '45%': { transform: 'translate3d(6px, -34px, 0) scale(1)', opacity: '0.95' },
          '78%': { opacity: '0.5' },
          '100%': { transform: 'translate3d(-4px, 2px, 0) scale(0.7)', opacity: '0' },
        },
        // Bubble rising from the seabed to the surface. Killed by its own
        // clip-path at the crest, so it reads as breaking the surface rather
        // than passing through it.
        'sea-bubble': {
          '0%': { transform: 'translate3d(0, 0, 0) scale(0.6)', opacity: '0' },
          '12%': { opacity: '0.8' },
          '50%': { transform: 'translate3d(9px, -26vh, 0) scale(1)' },
          '86%': { opacity: '0.7' },
          '100%': { transform: 'translate3d(-6px, -50vh, 0) scale(1.2)', opacity: '0' },
        },
        // The deck of the sea: the swell travelling across the whole surface, so
        // even the flat middle of the water is moving.
        'sea-drift': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(-96px, 0, 0)' },
        },
        // The assistant panel entering from the launcher that opened it.
        //
        // `fade-in`'s 4px dip is right for a menu anchored to its trigger, but
        // wrong for a tall panel: it reads as the panel dropping DOWN from above,
        // which is the opposite of where the user's finger is. A full 24px rise
        // from below, with a little scale, makes the panel look like it is being
        // pulled up out of the launcher.
        //
        // Only `transform` and `opacity` animate, so this stays on the
        // compositor and cannot trigger layout.
        'rise-in': {
          from: { opacity: '0', transform: 'translateY(24px) scale(0.97)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // The mobile counterpart: the panel drops DOWN from the top of the
        // screen. A phone opens the assistant at the bottom, so the surface has
        // to travel the full height and land above the launcher — a 24px rise
        // from the bottom is invisible at that distance. `translateY(-32px)` to
        // `0` is deliberately short: the panel is positioned by the container
        // (bottom-anchored), so this is a nudge INTO place, not a full
        // off-screen slide, which would need a viewport-height travel and fight
        // the layout on a short window. Transform/opacity only.
        'panel-drop': {
          from: { opacity: '0', transform: 'translateY(-32px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // --- Aqua AI panel: ONE SYMMETRIC PAIR (PROMPT 3, requirement A) ------
        //
        // The entrance and the exit are the same numbers run in opposite
        // directions: identical duration (0.3s), identical easing curve, the
        // same 40px travel and the same scale range. `panel-out` is literally
        // `panel-in` reversed, so open and close read as one motion played
        // forwards and backwards — no duration mismatch, no sudden jump, no
        // size change that only happens on the way out.
        //
        // The panel is anchored to the launcher (bottom-right), so the motion
        // is vertical: it rises out of the bubble on the way in and sinks back
        // into it on the way out.
        //
        // Only `transform` and `opacity` animate, so this stays on the
        // compositor and cannot trigger layout.
        'panel-in': {
          from: { opacity: '0', transform: 'translateY(40px) scale(0.96)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'panel-out': {
          from: { opacity: '1', transform: 'translateY(0) scale(1)' },
          to: { opacity: '0', transform: 'translateY(40px) scale(0.96)' },
        },
        // The backdrop's own entry. A plain opacity ramp (no travel) so the wash
        // beneath the panel simply resolves in, matching the panel's 0.3s on the
        // same curve. `fade-out` is reused for the exit, so both directions share
        // one definition and cannot drift apart.
        'aqua-backdrop-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'fade-out': {
          from: { opacity: '1' },
          to: { opacity: '0' },
        },
        // --- Card entry -----------------------------------------------
        // Cards arrive from their own side and settle: a card on the left of
        // the layout slides in from the left, one on the right from the right.
        // They are given a real distance (2.5rem) rather than a nudge so the
        // travel is legible, and they END at translateX(0) — the placed, stable
        // position — so nothing is left offset once the animation finishes.
        //
        // `both` fill mode is part of the contract: without it the card is
        // visible in its final spot for the first frame, then jumps back to the
        // offset and animates, which reads as a flicker. It also keeps the card
        // hidden (opacity 0) during any `animation-delay`, so staggered rows
        // arrive one at a time. Transform/opacity only, so this never triggers
        // layout.
        'slide-in-left': {
          from: { opacity: '0', transform: 'translate3d(-2.5rem, 0, 0)' },
          to: { opacity: '1', transform: 'translate3d(0, 0, 0)' },
        },
        'slide-in-right': {
          from: { opacity: '0', transform: 'translate3d(2.5rem, 0, 0)' },
          to: { opacity: '1', transform: 'translate3d(0, 0, 0)' },
        },
        // A card that sits on its own, or in the middle of a row, arrives by
        // ZOOMING IN from slightly smaller rather than by sliding from a side.
        //
        // The slide variants say "this card belongs to the left/right of
        // something"; a lone card has no side to belong to, so a lateral entry
        // would imply a relationship that is not there. Scaling up reads as the
        // card coming forward into place, which is the neutral arrival.
        //
        // 0.92 rather than something dramatic: the card must look like it was
        // always the right size, and a big zoom reads as a cartoon. `both` fill
        // (set in the `animation` block) holds the small, transparent state
        // through any stagger delay, so a row of cards arrives one at a time.
        'zoom-in': {
          from: { opacity: '0', transform: 'scale(0.92)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.95)', opacity: '0.7' },
          '70%': { transform: 'scale(1.1)', opacity: '0' },
          '100%': { transform: 'scale(1.1)', opacity: '0' },
        },
        // Typing indicator: one dot rising at a time, offset per dot by the
        // component's animationDelay so the three read as travelling.
        'typing-dot': {
          '0%, 60%, 100%': { transform: 'translateY(0)', opacity: '0.4' },
          '30%': { transform: 'translateY(-3px)', opacity: '1' },
        },

        // --- PROMPT 14: the sea-water opening animation --------------------
        // Waves that begin small and far away in the screen corners and swell
        // toward the viewer. `scale` is the whole trick: growing a shape is how
        // the eye reads something approaching, and it is the one transform that
        // genuinely conveys depth rather than sliding sideways.
        //
        // TRANSLATE BY A PERCENTAGE OF *THE ELEMENT'S OWN* SIZE is deliberate.
        // A wave anchored to a corner is much smaller than the viewport for the
        // first half of its life, so a `translateX(-40%)` on the element moves
        // it a fifth of what it looks like on screen — the motion would be
        // inconsistent with its own size and read as a jump. Percentages on the
        // element keep the movement proportional to what is drawn.

        // A wave arriving from the LEFT corner: scales up toward the viewer while
        // drifting right and down. Held at 100% by the component's `both` fill,
        // so the wave stays expanded as the overlay fades rather than snapping
        // back to its far-away size at the end.
        'intro-wave-left': {
          // PURE SCALE, NO HORIZONTAL TRANSLATE. The layer is anchored to the
          // bottom-left corner and is 170vw wide; scaling it from 0.12 to 1.35
          // grows it out of that corner and always past the opposite edge. Any
          // horizontal translate pulled the layer's far edge INTO frame and
          // produced a visible vertical seam where its box ended — which is the
          // left/right "ending" the brief forbids. Vertical drift is kept (it adds
          // the feeling of the swell rising toward the viewer) but horizontal
          // movement is zero.
          '0%': {
            transform: 'translate3d(0, 0, 0) scale(0.12)',
            opacity: '0.25',
          },
          '45%': { transform: 'translate3d(0, 10%, 0) scale(0.6)', opacity: '0.7' },
          '100%': {
            transform: 'translate3d(0, 26%, 0) scale(1.35)',
            opacity: '1',
          },
        },
        // The mirror from the RIGHT corner. Deliberately NOT a negative scaleX
        // of the same animation: that would be cheaper to write and would make
        // the two waves move in lockstep, which is exactly the symmetry the
        // brief asks to avoid. The keyframes differ in their intermediate
        // offsets so the two fronts arrive at slightly different moments.
        'intro-wave-right': {
          '0%': {
            transform: 'translate3d(0, 0, 0) scale(0.12)',
            opacity: '0.25',
          },
          '45%': { transform: 'translate3d(0, 12%, 0) scale(0.58)', opacity: '0.7' },
          '100%': {
            transform: 'translate3d(0, 28%, 0) scale(1.35)',
            opacity: '1',
          },
        },
        // The crest of an approaching wave, riding forward *within* the body of
        // water that is already growing. This is what makes the edge read as a
        // moving wave surface rather than a scaled-up static shape.
        'intro-crest': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '50%': { transform: 'translate3d(-3%, 0, 0)' },
          '100%': { transform: 'translate3d(0, 0, 0)' },
        },
        // A swell scrolling sideways INSIDE the water body, so the water has
        // visible internal movement travelling against the approach.
        'intro-swell': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(-50%, 0, 0)' },
        },
        // Caustic light washing across the near face of the water. Runs
        // independently of the approach so the surface is never perfectly still
        // once it has arrived.
        'intro-shimmer': {
          '0%, 100%': { opacity: '0.35' },
          '50%': { opacity: '0.75' },
        },
        // The whole overlay clearing away at the end. Short and ease-in, so the
        // hand-off to the Home page reads as the water receding rather than as
        // the page being swapped.
        'intro-out': {
          '0%': { opacity: '1' },
          '100%': { opacity: '0' },
        },
        // The wordmark settling into place while the water is still moving.
        'intro-mark': {
          '0%': { transform: 'translate3d(0, 10px, 0)', opacity: '0' },
          '100%': { transform: 'translate3d(0, 0, 0)', opacity: '1' },
        },

        // --- Water background -------------------------------------------
        // Every one of these animates only transform/opacity, so the backdrop
        // stays on the compositor and never triggers layout or paint.

        // Falling rain drop. Starts above the viewport and lands past the
        // bottom, so a drop is never seen appearing or vanishing mid-screen.
        'rain-fall': {
          '0%': { transform: 'translate3d(0, -30vh, 0)' },
          '100%': { transform: 'translate3d(6px, 130vh, 0)' },
        },
        // A droplet rising from the seabed, swaying as it goes.
        'bubble-rise': {
          '0%': { transform: 'translate3d(0, 0, 0) scale(0.7)', opacity: '0' },
          '12%': { opacity: '0.75' },
          '50%': { transform: 'translate3d(14px, -55vh, 0) scale(1)' },
          '88%': { opacity: '0.6' },
          '100%': { transform: 'translate3d(-10px, -110vh, 0) scale(1.15)', opacity: '0' },
        },
        // Caustic light drifting across the surface. Two directions so the
        // washes never sync up and reveal the loop.
        'drift-slow': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '50%': { transform: 'translate3d(6%, -4%, 0) scale(1.12)' },
        },
        'drift-reverse': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1.08)' },
          '50%': { transform: 'translate3d(-7%, 5%, 0) scale(1)' },
        },
        // Wave bands. The SVG is twice the viewport wide and translates by
        // exactly half, so the loop is seamless.
        'wave-slow': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(-50%, 0, 0)' },
        },
        'wave-mid': {
          '0%': { transform: 'translate3d(-50%, 0, 0)' },
          '100%': { transform: 'translate3d(0, 0, 0)' },
        },
        'wave-fast': {
          '0%': { transform: 'translate3d(0, 2%, 0)' },
          '100%': { transform: 'translate3d(-50%, 2%, 0)' },
        },
        // The waterline itself breathing up and down.
        'waterline': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-3px)' },
        },
        // A filled vessel visibly draining and refilling.
        'water-level': {
          '0%, 100%': { transform: 'translateY(18%)' },
          '50%': { transform: 'translateY(-6%)' },
        },
        // Loading droplet: falls in, splashes back up, settles.
        'drop-bounce': {
          '0%, 100%': { transform: 'translateY(-3px) scaleY(1)' },
          '45%': { transform: 'translateY(3px) scaleY(0.7)' },
          '70%': { transform: 'translateY(0) scaleY(1.15)' },
          '85%': { transform: 'translateY(1px) scaleY(1)' },
        },
        // The status dot on the country overview's state list: a soft pulse
        // (the halo breathes around the dot) rather than a hard blink, so a
        // long list of states does not strobe. `dot-blink` is the hard 1s
        // blink the brief's "animated/blinking status dots" wording asks for.
        'dot-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.25' },
        },
        // The expanding halo behind the dot: grows outward and fades, in the
        // same language as the app's ripple animation so it reads as AquaGuard.
        'dot-halo': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '70%': { transform: 'scale(1.9)', opacity: '0' },
          '100%': { transform: 'scale(1.9)', opacity: '0' },
        },
        // The ring the drop leaves behind: expands and fades to nothing.
        'ripple': {
          '0%, 30%': { transform: 'scale(0.35)', opacity: '0' },
          '45%': { opacity: '0.85' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
        // Tiled rain field covering the whole document. It travels exactly one
        // tile (190px, matching backgroundSize) so the loop is seamless — any
        // other distance would make the pattern visibly jump on repeat.
        'rain-field': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(0, 190px, 0)' },
        },
        // Broad swell bands drifting up the page body, one 128px tile per cycle.
        'swell': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(0, -128px, 0)' },
        },
        // THE SPLASH SURFACE. A wave band travels exactly half its own width,
        // because the SVG that carries it is rendered at 200% width and holds
        // two identical copies of the same wave: when the first has moved one
        // full wave out of view, the second is exactly where the first started,
        // so the reset is invisible. Any other distance would make the water
        // visibly jump once per cycle.
        //
        // `translate3d` keeps it on the GPU compositor, and 50% of the 200%-wide
        // element is precisely one period of the sine that the path is drawn
        // from — the two are the same number for a reason, not by coincidence.
        'splash-wave-drift': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(-50%, 0, 0)' },
        },
        // The thin bar under the wordmark, so the two-second hold reads as
        // deliberate rather than as a stall. Travels its own width and resets.
        'splash-shimmer': {
          '0%': { transform: 'translate3d(-100%, 0, 0)' },
          '100%': { transform: 'translate3d(300%, 0, 0)' },
        },

        // --- 3D water droplet -------------------------------------------
        // A hanging droplet swells under its own weight, pinches off, and
        // snaps back. The asymmetry matters: it spends most of the cycle
        // hanging still, then releases quickly — a symmetric sine would look
        // like it is breathing in and out rather than about to fall.
        'drop-drip': {
          '0%, 55%': { transform: 'translateY(0) scale(1, 1)' },
          '70%': { transform: 'translateY(3px) scale(0.94, 1.12)' },
          '78%': { transform: 'translateY(1px) scale(1.04, 0.94)' },
          '84%': { transform: 'translateY(0) scale(1, 1)' },
          '100%': { transform: 'translateY(0) scale(1, 1)' },
        },
        // The catchlight drifting across the drop, which is what sells a
        // glossy wet surface: a still highlight reads as printed-on plastic.
        'gloss-shimmer': {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)', opacity: '0.95' },
          '50%': { transform: 'translate(2px, 1.5px) scale(1.12)', opacity: '0.75' },
        },
        // The shadow under the droplet tightening as the drop stretches.
        'drop-shadow': {
          '0%, 55%': { transform: 'scale(1)', opacity: '0.25' },
          '70%': { transform: 'scale(0.86)', opacity: '0.16' },
          '84%, 100%': { transform: 'scale(1)', opacity: '0.25' },
        },

        // --- AquaGuard logo ---------------------------------------------
        // Ripples expanding out of the droplet, fading as they travel.
        'logo-ripple': {
          '0%': { transform: 'scale(0.55)', opacity: '0' },
          '20%': { opacity: '0.7' },
          '100%': { transform: 'scale(2.1)', opacity: '0' },
        },
        // The droplet at the network's input, gently breathing.
        'logo-drop-breathe': {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.07)' },
        },
        // A hidden node firing: a bright flash that decays.
        'node-fire': {
          '0%, 100%': { opacity: '0.55', transform: 'scale(1)' },
          '25%': { opacity: '1', transform: 'scale(1.28)' },
          '50%': { opacity: '0.7', transform: 'scale(1)' },
        },
        // The output node breathing brighter than the hidden ones.
        'verdict-glow': {
          '0%, 100%': { opacity: '0.75', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.16)' },
        },

        // --- Home page guide rail ---------------------------------------
        //
        // The rail now advances ONE CARD AT A TIME rather than sliding the whole
        // list continuously. Each card is the same width, so moving the track by
        // exactly -100% of one card lands the next card precisely where the last
        // one was — a step, not a drift.
        //
        // (A `guide-step` keyframe — translating a track by one card width — was
        // removed when the rail moved to the `show-six` opacity window: the cards
        // are stacked in place and cross-faded, so nothing translates and there
        // is no step distance to keep in sync with a card width.)
        //
        // --- Admin console -------------------------------------------------
        // Bubbles rising through the whole console, and the scan sweep that
        // travels down it. Named with a `console-` prefix so they are
        // unmistakably the console's own and cannot collide with the loaders'.
        'console-bubble': {
          '0%': { transform: 'translate3d(0, 0, 0) scale(0.6)', opacity: '0' },
          '12%': { opacity: '0.7' },
          '85%': { opacity: '0.45' },
          '100%': { transform: 'translate3d(0, -100vh, 0) scale(1.1)', opacity: '0' },
        },
        // The scan line: a soft band travelling the full height of the console
        // and fading out before it reaches the bottom, so the loop has no
        // visible seam.
        'console-scan': {
          '0%': { transform: 'translate3d(0, -6rem, 0)', opacity: '0' },
          '10%': { opacity: '1' },
          '85%': { opacity: '0.6' },
          '100%': { transform: 'translate3d(0, 100vh, 0)', opacity: '0' },
        },
        // The sea swell INSIDE a step card: the card's water surface rising and
        // falling in place.
        //
        // This replaced `water-wipe`, which swept a curved sheet left-to-right
        // across the card. That read as a shape entering and leaving — it had a
        // visible start point at the left edge and an end point at the right, and
        // a hard edge on both. A real surface has neither: it just moves and
        // down. So the motion is now VERTICAL, the travel is small (a shallow
        // swell rather than a wave breaking), and there is no translateX at all,
        // which is what removes the cut on the left and right edges.
        //
        // The horizontal component is a slow lateral drift INSIDE the vertical
        // one, so the crest is never perfectly still — but it is small enough
        // that the band's ends stay off-screen for the whole cycle.
        //
        // (The old `water-wipe` keyframe is deliberately left in place below for
        // anyone still referencing it; nothing in the app uses it now.)
        'sea-swell-card': {
          '0%, 100%': { transform: 'translate3d(0, 0.5rem, 0)' },
          '50%': { transform: 'translate3d(-1.5%, -0.6rem, 0)' },
        },
        'water-wipe': {
          '0%': { transform: 'translate3d(-100%, 0, 0)' },
          '60%': { transform: 'translate3d(0%, 0, 0)' },
          '100%': { transform: 'translate3d(100%, 0, 0)' },
        },
        // Ripples on the card during a swipe — the water reading of the motion,
        // expanding and fading like rings on a disturbed surface.
        'water-ripple': {
          '0%': { transform: 'scale(0.6)', opacity: '0' },
          '35%': { opacity: '0.55' },
          '100%': { transform: 'scale(1.8)', opacity: '0' },
        },
        // --- Water INSIDE each card --------------------------------------
        // Bubbles rising through the card's own background, behind its text.
        //
        // The travel is expressed in `rem` rather than `vh` on purpose: a card is
        // a small fixed box, so a viewport-relative distance would overshoot it on
        // a tall window and barely move on a short one. A bubble must start below
        // the card's bottom edge and end past its top edge whatever the screen.
        'card-bubble': {
          '0%': { transform: 'translate3d(0, 0, 0) scale(0.5)', opacity: '0' },
          '15%': { opacity: '0.85' },
          '80%': { opacity: '0.6' },
          '100%': { transform: 'translate3d(4px, -16rem, 0) scale(1.1)', opacity: '0' },
        },
        // The waterline inside the card, breathing up and down. Distinct from the
        // loader's rise: this never fills, it just shifts, so the card's readable
        // area stays constant.
        'card-waterline': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0)' },
          '50%': { transform: 'translate3d(-2%, -6px, 0)' },
        },
        // Caustic light drifting across the card's water, slow and out of phase
        // between cards so a row of them never pulses in unison.
        'card-caustics': {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)', opacity: '0.5' },
          '50%': { transform: 'translate3d(6%, -4%, 0) scale(1.18)', opacity: '0.75' },
        },
        // --- STEP 31: the Location Prediction guide cards ------------------
        //
        // These three are deliberately SEPARATE from the ones above. The step
        // rail's cards are a carousel with a moving track, so their motion has to
        // be driven by a shared clock; these cards are a static grid that scrolls,
        // so their motion has to be driven by the SCROLL POSITION instead.
        //
        // `guide-card-in` is the entrance: the card rises and settles, and it ends
        // on the identity transform. Because it ends at `translateY(0) scale(1)`
        // rather than at nothing, the card can also use this as its HOVER state —
        // adding the animation to a `hover:` variant replays the entrance from the
        // lifted position, so a pointer produces a small settle rather than a jump.
        'guide-card-in': {
          '0%': { opacity: '0', transform: 'translateY(18px) scale(0.97)' },
          '60%': { opacity: '1', transform: 'translateY(-2px) scale(1.005)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // The badge's halo, so a card's step number breathes. Offset per card by an
        // inline `animationDelay`, which is what stops a row of six pulsing in
        // unison and turning the section into a single blinking block.
        'guide-badge-halo': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgb(14 165 233 / 0.35)' },
          '50%': { boxShadow: '0 0 0 6px rgb(14 165 233 / 0)' },
        },
        // The connector line that runs down the left of the list on a narrow
        // screen: a slow downward wash, so the eye is drawn from one step to the
        // next rather than being left to infer the order from the numbers alone.
        'guide-flow': {
          '0%': { transform: 'translateY(-40%) scaleY(0.4)' },
          '50%': { transform: 'translateY(0%) scaleY(1)' },
          '100%': { transform: 'translateY(40%) scaleY(0.4)' },
        },
        // --- the one-at-a-time card window ------------------------------
        //
        // One card is visible only during its own slice of the cycle.
        //
        // WHY THIS IS NOT PARAMETERISED. The obvious version of this keyframe
        // takes its boundaries from custom properties — `var(--slot-start) { … }`
        // as a keyframe SELECTOR. That is invalid CSS: a keyframe selector must be
        // a percentage (or `from`/`to`), so the browser drops the whole rule and
        // the rail silently does nothing. Keyframe selectors simply cannot be
        // dynamic.
        //
        // So the cycle is expressed as FIXED proportions instead, and the number
        // of cards is fixed with it: the rail is six steps, and every card's
        // window is one sixth of the cycle with a short crossfade at each
        // boundary. Easing `linear` is required — any easing would bunch the
        // windows unevenly and two cards would be visible at once.
        //
        // Opacity only: no transform, so hidden cards cannot affect layout, and
        // six of these can loop indefinitely for nothing on the compositor.
        'show-six': {
          '0%': { opacity: '0' },
          '1.2%': { opacity: '1' },
          '15.5%': { opacity: '1' },
          '16.7%': { opacity: '0' },
          '100%': { opacity: '0' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out',
        'rise-in': 'rise-in 0.26s cubic-bezier(0.22, 1, 0.36, 1)',
        // --- Aqua AI panel (PROMPT 3, requirement A): one symmetric pair.
        // Same 0.3s duration and identical curve in both directions, so closing
        // is literally the opening animation reversed. The component's close
        // timer matches this 300ms.
        'panel-in': 'panel-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both',
        'panel-out': 'panel-out 0.3s cubic-bezier(0.22, 1, 0.36, 1) both',
        // THE BACKDROP FADES ON THE PANEL'S OWN CLOCK.
        //
        // These two were 0.25s ease-out in and 0.45s ease-in out, while the
        // panel was 0.3s in both directions — so the scrim outlived the panel by
        // 150ms on close and the whole close read as asymmetric: the box was gone
        // but a dark wash lingered, then snapped off. Both directions are now
        // 0.3s on the SAME curve the panel uses, so the scrim and the box move as
        // one motion and open/close are exact mirrors of each other.
        'aqua-backdrop-in': 'aqua-backdrop-in 0.3s cubic-bezier(0.22, 1, 0.36, 1) both',
        'aqua-backdrop-out': 'fade-out 0.3s cubic-bezier(0.22, 1, 0.36, 1) both',
        // `both` so the card holds its start (hidden, offset) through any delay
        // and its end (settled) afterwards — see the keyframe comment.
        'slide-in-left': 'slide-in-left 0.6s cubic-bezier(0.22, 1, 0.36, 1) both',
        'slide-in-right': 'slide-in-right 0.6s cubic-bezier(0.22, 1, 0.36, 1) both',
        'zoom-in': 'zoom-in 0.55s cubic-bezier(0.22, 1, 0.36, 1) both',
        'rain-fill': 'rain-fill 1s linear infinite',
        'sea-rise': 'sea-rise 3s cubic-bezier(0.45, 0, 0.25, 1) infinite',
        'sea-foam': 'sea-foam 3s ease-in-out infinite',
        'sea-bob': 'sea-bob 3s ease-in-out infinite',
        'sea-caustics': 'sea-caustics 7s ease-in-out infinite',
        // Deliberately NOT 3s: it runs against the fill's own duration so the two
        // waves never resynchronise into a pattern the eye can predict.
        'sea-surface-drift': 'sea-surface-drift 7s ease-in-out infinite',
        'sea-spray': 'sea-spray 1.7s ease-out infinite',
        'sea-bubble': 'sea-bubble 14s linear infinite',
        'sea-drift': 'sea-drift 7s linear infinite',
        // PROMPT 14: the opening animation. Every approach is `both`-filled so
        // the wave HOLDS its expanded state while the overlay fades out — with a
        // `forwards`-less animation the wave would spring back to scale(0.12)
        // at the end, which looks like the water retreating and is the exact
        // opposite of what the brief describes.
        //
        // The timing functions matter for the look, not the speed:
        // `cubic-bezier(0.22, 1, 0.36, 1)` is the same ease-out used elsewhere
        // in the console for entrances, and it is what makes the wave *accelerate*
        // into the screen and then settle, the way something coming toward you
        // actually behaves.
        'intro-wave-left': 'intro-wave-left 3s cubic-bezier(0.22, 1, 0.36, 1) both',
        'intro-wave-right': 'intro-wave-right 3s cubic-bezier(0.2, 1, 0.35, 1) both',
        'intro-crest': 'intro-crest 3s ease-in-out infinite',
        'intro-swell': 'intro-swell 2.6s linear infinite',
        'intro-shimmer': 'intro-shimmer 1.9s ease-in-out infinite',
        'intro-out': 'intro-out 0.4s ease-in both',
        'intro-mark': 'intro-mark 0.9s cubic-bezier(0.22, 1, 0.36, 1) 1.35s both',
        'pulse-ring': 'pulse-ring 1.8s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'typing-dot': 'typing-dot 1.2s ease-in-out infinite',
        'rain-fall': 'rain-fall 1.6s linear infinite',
        'bubble-rise': 'bubble-rise 12s linear infinite',
        'drift-slow': 'drift-slow 24s ease-in-out infinite',
        'drift-reverse': 'drift-reverse 32s ease-in-out infinite',
        'wave-slow': 'wave-slow 26s linear infinite',
        'wave-mid': 'wave-mid 18s linear infinite',
        'wave-fast': 'wave-fast 12s linear infinite',
        'waterline': 'waterline 4s ease-in-out infinite',
        'water-level': 'water-level 5s ease-in-out infinite',
        'drop-bounce': 'drop-bounce 1.6s ease-in-out infinite',
        'ripple': 'ripple 1.6s ease-out infinite',
        'dot-blink': 'dot-blink 1.2s ease-in-out infinite',
        'dot-halo': 'dot-halo 1.2s ease-out infinite',
        'rain-field': 'rain-field 2.4s linear infinite',
        'swell': 'swell 16s linear infinite',
        // The Home splash. The wave's DURATION is set inline per band (three
        // bands, three speeds) rather than here, so this only registers the
        // keyframe so Tailwind emits it at all; the shimmer is a fixed cycle.
        'splash-wave-drift': 'splash-wave-drift 12s linear infinite',
        'splash-shimmer': 'splash-shimmer 1.1s ease-in-out infinite',
        'drop-drip': 'drop-drip 4.5s ease-in-out infinite',
        'gloss-shimmer': 'gloss-shimmer 5s ease-in-out infinite',
        'drop-shadow': 'drop-shadow 4.5s ease-in-out infinite',
        'logo-ripple': 'logo-ripple 1.8s ease-out infinite',
        'logo-drop-breathe': 'logo-drop-breathe 3s ease-in-out infinite',
        'node-fire': 'node-fire 2s ease-in-out infinite',
        'verdict-glow': 'verdict-glow 2s ease-in-out infinite',
        // The card's surface rising and falling. Slow and eased, so it reads as a
        // swell rather than a bounce.
        'sea-swell-card': 'sea-swell-card 7s ease-in-out infinite',
        // Kept for compatibility; the card water moved to `sea-swell-card`.
        'water-wipe': 'water-wipe 5s cubic-bezier(0.33, 0, 0.67, 1) infinite',
        'water-ripple': 'water-ripple 2.5s ease-out infinite',
        // Set per-bubble inline, so only the fallback duration lives here.
        'console-bubble': 'console-bubble 16s linear infinite',
        'console-scan': 'console-scan 9s linear infinite',
        'card-bubble': 'card-bubble 7s linear infinite',
        'card-waterline': 'card-waterline 6s ease-in-out infinite',
        'card-caustics': 'card-caustics 9s ease-in-out infinite',
        // Duration and delay are set per card inline (the delay is what puts each
        // card on a different slice of the shared clock); the duration here is
        // only the fallback before the inline value lands. `linear` is part of
        // the contract, not a taste choice — see the keyframe comment.
        'show-six': 'show-six 30s linear infinite',
        // The guide card entrance. `both` is what makes the stagger work: it holds
        // the card at its `from` state through its own `animationDelay`, so the six
        // really do arrive one after another instead of all on the first frame.
        'guide-card-in': 'guide-card-in 0.6s cubic-bezier(0.22, 1, 0.36, 1) both',
        // Delay is set per card inline; this is only the fallback.
        'guide-badge-halo': 'guide-badge-halo 2.6s ease-in-out infinite',
        'guide-flow': 'guide-flow 3.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
