const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

// Renders the generated PDFs with pdf.js fully inlined (main thread "fake
// worker" mode): the api bundle sets window.pdfjsLib, the worker bundle sets
// window.pdfjsWorker, and pdf.js finds it via _mainThreadWorkerMessageHandler.
const api = fs.readFileSync(path.join(ROOT, 'package/build/pdf.min.js'), 'utf8')
const worker = fs.readFileSync(path.join(ROOT, 'package/build/pdf.worker.min.js'), 'utf8')
const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')
const multi = fs.readFileSync(path.join(ROOT, 'qa_report_multi.pdf')).toString('base64')

const hostPath = path.join(ROOT, 'pdf_render_host4.html')
fs.writeFileSync(hostPath, `<!doctype html><html><body>
<textarea id="out" style="display:none"></textarea>
<script>${api}
window.pdfjsWorker = window.pdfjsWorker || {}
// The worker UMD attaches its exports to the global under its own key; give the
// fake-worker loader what it looks for.
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
window.__render = async function (singleB64, multiB64) {
  const pdfjsLib = window.pdfjsLib
  const out = []
  for (const [name, b64] of Object.entries({ single: singleB64, multi: multiB64 })) {
    if (!b64) continue
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
  document.title = 'RENDER_DONE'
}
document.title = 'HOST_READY ' + typeof window.pdfjsLib
<\/script></body></html>`)

async function main() {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  await p.goto('file:///' + hostPath.replace(/\\/g, '/'), { waitUntil: 'load' })
  console.log('host state:', await p.title())
  await p.addScriptTag({
    content: `window.__render(${JSON.stringify(single)}, ${JSON.stringify(multi)})
      .catch(e => { document.title = 'RENDER_ERR ' + e.message })`,
  })
  for (let i = 0; i < 45; i++) {
    await p.waitForTimeout(2000)
    const t = await p.title()
    if (t.startsWith('RENDER')) { console.log(t); break }
    if (i % 5 === 0) console.log('waiting...', t)
  }
  const out = await p.evaluate(() => (document.getElementById('out') || {}).value || '')
  if (!out) { console.error('NO OUTPUT'); await b.close(); process.exit(1) }
  JSON.parse(out).forEach((pg) => {
    fs.writeFileSync(path.join(ROOT, `pdf_${pg.name}.png`), Buffer.from(pg.dataUrl, 'base64'))
    console.log('wrote', pg.name)
  })
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
