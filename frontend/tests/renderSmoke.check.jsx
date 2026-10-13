/**
 * Entry for the render smoke-check. esbuild bundles this together with the
 * components under test (resolving the `@/` alias itself), so what runs is the
 * same transformed code the browser gets — Node's own JSX handling is not
 * involved at all.
 */
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import WaterLoader from '@/components/WaterLoader'

const html = renderToStaticMarkup(h(WaterLoader, { label: 'Loading...' }))

const report = {
  ok: html.length > 0,
  length: html.length,
  seaRise: html.includes('sea-rise'),
  foam: html.includes('sea-foam'),
  sprayDrops: (html.match(/sea-spray/g) || []).length,
  bubbles: (html.match(/sea-bubble/g) || []).length,
  // The curved fill boundary must be the polygon clip, not a straight inset.
  waveClip: html.includes('sea-rise') && !html.includes('inset(0% 0% 0% 0%)'),
  // The previous implementation's markers must be absent.
  legacyWaterFill: html.includes('water-fill'),
  legacyWaveBands: /wave-(mid|slow|fast)/.test(html),
  labelRendered: html.includes('Loading...'),
}

console.log(JSON.stringify(report, null, 2))
