const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

// Renders the generated PDFs with pdf.js. The pdf.js UMD bundle is inlined into
// a host page; because patchright's evaluate runs in a SEPARATE world from page
// scripts, the bridge passes the library through document.title-free channels:
// the host script stores the module on `window.__pdfjs`, and we read it via
// DOM-based handshake (a hidden textarea) since window props don't cross worlds.
const pdfjs = fs.readFileSync(path.join(ROOT, 'package/build/pdf.min.js'), 'utf8')
const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')
const multi = fs.readFileSync(path.join(ROOT, 'qa_report_multi.pdf')).toString('base64')

const hostPath = path.join(ROOT, 'pdf_render_host3.html')
fs.writeFileSync(hostPath, `<!doctype html><html><body>
<textarea id="out" style="display:none"></textarea>
<script>${pdfjs}
window.__render = async function (singleB64, multiB64) {
  const pdfjsLib = window.pdfjsLib
  pdfjsLib.GlobalWorkerOptions.workerSrc = ''
  const out = []
  for (const [name, b64] of Object.entries({ single: singleB64, multi: multiB64 })) {
    const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    const doc = await pdfjsLib.getDocument({ data }).promise
    for (let i = 1; i <= doc.numPages; i++) {
      const pg = await doc.getPage(i)
      const vp = pg.getViewport({ scale: 1.4 })
      const cv = document.createElement('canvas')
      cv.width = vp.width; cv.height = vp.height
      await pg.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise
      out.push({ name: name + '_p' + i, dataUrl: cv.toDataURL('image/png').split(',')[1] })
    }
  }
  document.getElementById('out').value = JSON.stringify(out)
  window.__done = true
}
window.__pdfReady = typeof window.pdfjsLib === 'object'
<\/script></body></html>`)

async function main() {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  await p.goto('file:///' + hostPath.replace(/\\/g, '/'), { waitUntil: 'load' })
  // addScriptTag runs in the PAGE's own world, so it can see __render.
  await p.addScriptTag({ content: `window.__render(${JSON.stringify(single)}, ${JSON.stringify(multi)}).catch(e => { window.__err = e.message })` })
  // The evaluate world cannot see page-world window props, so poll the DOM:
  // __render writes its JSON result into the #out textarea when finished.
  let out = ''
  for (let i = 0; i < 60; i += 1) {
    await p.waitForTimeout(2000)
    out = await p.evaluate(() => (document.getElementById('out') || {}).value || '')
    if (out) break
  }
  if (!out) { console.error('RENDER TIMED OUT'); await b.close(); process.exit(1) }
  JSON.parse(out).forEach((pg) => {
    fs.writeFileSync(path.join(ROOT, `pdf_${pg.name}.png`), Buffer.from(pg.dataUrl, 'base64'))
    console.log('wrote', pg.name)
  })
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
