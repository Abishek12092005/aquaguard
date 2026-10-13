/**
 * Renders the Home page to static markup.
 *
 * Home reads the signed-in user from the auth context, so `useAuth` is stubbed
 * here — the context provider is not what is under test, and mounting the real
 * one would drag in the whole router and API layer. The page's own structure is
 * what this checks.
 */
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import Home from '@/pages/Home'

const html = renderToStaticMarkup(h(Home))

console.log(
  JSON.stringify(
    {
      ok: html.length > 0,
      length: html.length,
      // The one-at-a-time swipe rail: one card per step, its own slot window,
      // and the water wipe that carries each card in.
      // Per-card water scene: bubbles, the breathing waterline, the caustics.
      cardBubbles: (html.match(/card-bubble/g) || []).length,
      cardWaterline: (html.match(/card-waterline/g) || []).length,
      cardCaustics: (html.match(/card-caustics/g) || []).length,
      waterWipe: html.includes('water-wipe'),
      waveSheet: html.includes('water-wipe') && html.includes('C160,0'),
      // The text must sit on its own surface, above the water layers.
      textSurface: html.includes('bg-white/75') && html.includes('backdrop-blur-[2px]'),
      progressDots: (html.match(/rounded-full bg-aqua-500\/30/g) || []).length,
      // Each card reports its position, so "one at a time" is legible in text.
      stepCounters: (html.match(/Step \d of 6/g) || []).length,
      stepCards: (html.match(/Step \d/g) || []).length,
      sections: [
        'How it works, end to end',
        'What you need to enter',
        'Reading the result',
        'What unsafe water actually costs you',
      ].filter((s) => html.includes(s)),
      // Content spot-checks, so an empty shell cannot pass.
      mentionsPh: html.includes('pH'),
      mentionsTurbidity: html.includes('Turbidity'),
      mentionsLabCaveat: html.includes('not a substitute for laboratory testing'),
      stepTitles: ['Open Water Prediction', 'Enter the five readings', 'Submit and read the verdict'].filter(
        (t) => html.includes(t),
      ),

      // STEP 31: the Location Prediction guide. Six cards, in order, animated,
      // responsive and with their copy present — and the four blocks above it
      // still there, because this section was added to the page rather than in
      // place of anything on it.
      guideCards: (html.match(/data-testid="location-guide-card"/g) || []).length,
      guideStepsListed: (html.match(/Step \d of 6/g) || []).length,
      guideAnimation: html.includes('animate-guide-card-in'),
      guideBadgeHalo: html.includes('animate-guide-badge-halo'),
      guideConnector: html.includes('animate-guide-flow'),
      // Responsive: three layouts, one column / two columns / three columns.
      guideBreakpoints: ['sm:grid-cols-2', 'lg:grid-cols-3'].filter((c) => html.includes(c)),
      // Motion is gated, so a reduced-motion user gets the cards visible.
      guideMotionSafeOnly: html.includes('motion-safe:animate-guide-card-in'),
      // The six titles from the brief, and the searchable nouns step 1 lists.
      guideTitles: [
        'Search a Location',
        'Select the Location',
        'Check Water Source',
        'View Water Parameters',
        'Analyze Water Quality',
        'View Result',
      ].filter((t) => html.includes(t)),
      guideNouns: ['Pincode', 'Company, college or school', 'Shop, landmark or building'].filter(
        (t) => html.includes(t),
      ),
      // Card 4's five parameters and card 6's three verdicts.
      guideVerdicts: ['SAFE', 'MODERATE', 'UNSAFE'].filter((t) => html.includes(t)),
      // The section links onward to the screen it describes.
      guideLinksToLocation: html.includes('Open Location Prediction') && html.includes('href="/location"'),
    },
    null,
    2,
  ),
)
