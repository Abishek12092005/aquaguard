const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

const pdfjs = fs.readFileSync(path.join(ROOT, 'package/build/pdf.min.js'), 'utf8')
const worker = fs.readFileSync(path.join(ROOT, 'package/build/pdf.worker.min.js'), 'utf8')
const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')

const hostPath = path.join(ROOT, 'pdf_zoom_host.html')

// build host like qa_render_final
function buildHost() {
  return `<!doctype html><html><body>
<textarea id="out" style="display:none"></textarea>
<script>${pdfjs}
window.pdfjsWorker = window.pdfjsWorker || {}
if (!window.pdfjsWorker.WorkerMessageHandler && window['pdfjs-dist/build/pdf.worker']) {
  window.pdfjsWorker = window['pdfjs-dist/build/pdf.worker']
}
<\/script>
<script>${worker}
if (!window.pdfjsWorker.WorkerMessageHandler && window['pdfjs-dist/build/pdf.worker']) {
  window.pdfjsWorker = window['pdfjs-dist/build/pdf.worker']
}
<\/script>
<script>
window.__render = async function (b64, scale, clip) {
  const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const doc = await window.pdfjsLib.getDocument({ data }).promise
  const pg = await doc.getPage(1)
  const vp = pg.getViewport({ scale })
  const cv = document.createElement('canvas')
  cv.width = vp.width; cv.height = vp.height
  await pg.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise
  // Crop: clip is [x0, y0, x1, y1] in viewport pixels (y from TOP).
  const c2 = document.createElement('canvas')
  c2.width = clip[2] - clip[0]; c2.height = clip[3] - clip[1]
  c2.getContext('2d').drawImage(cv, clip[0], clip[1], c2.width, c2.height, 0, 0, c2.width, c2.height)
  document.getElementById('out').value = c2.toDataURL('image/png').split(',')[1]
  document.title = 'RENDER_DONE'
}
document.title = 'HOST_READY'
<\/script></body></html>`
}

async function main() {
  fs.writeFileSync(hostPath, buildHost())
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  await p.goto('file:///' + hostPath.replace(/\\/g, '/'), { waitUntil: 'load' })
  // A4 at scale 3 = 595*3=1785 x 842*3=2526 px. Crop the middle band where the
  // watermark sits (centre of page).
  const clip = [500, 800, 1285, 1750]
  await p.addScriptTag({ content: `window.__render(${JSON.stringify(single)}, 3, ${JSON.stringify(clip)}).catch(e => { document.title = 'RENDER_ERR ' + e.message })` })
  for (let i = 0; i < 45; i++) {
    await p.waitForTimeout(2000)
    if ((await p.title()).startsWith('RENDER')) break
  }
  const out = await p.evaluate(() => (document.getElementById('out') || {}).value || '')
  if (!out) { console.error('NO OUTPUT'); await b.close(); process.exit(1) }
  fs.writeFileSync(path.join(ROOT, 'pdf_watermark_zoom.png'), Buffer.from(out, 'base64'))
  console.log('wrote pdf_watermark_zoom.png')
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
