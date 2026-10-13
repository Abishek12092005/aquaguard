const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')

// Renders both generated PDFs to PNGs. The pdf.js bundle is INLINED into the
// host page as a <script> body (file:// external scripts are blocked by
// Chromium's local-file restrictions; inline scripts always run).
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'

async function main() {
  const b = await chromium.launch({ headless: true })
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  p.on('console', (m) => { if (m.type() === 'error') console.log('C:', m.text().slice(0, 200)) })

  const pdfjs = fs.readFileSync(path.join(ROOT, 'package/build/pdf.min.js'), 'utf8')
  const hostPath = path.join(ROOT, 'pdf_render_host2.html').replace(/\\/g, '/')
  fs.writeFileSync(hostPath, `<!doctype html><html><body>
<script>${pdfjs}</script>
<script>window.__ready = typeof window.pdfjsLib === 'object'</script>
</body></html>`)
  await p.goto('file:///' + hostPath, { waitUntil: 'load' })
  const t = await p.evaluate(() => typeof window.pdfjsLib)
  console.log('lib:', t)
  if (t !== 'object') { await b.close(); process.exit(1) }

  const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')
  const multi = fs.readFileSync(path.join(ROOT, 'qa_report_multi.pdf')).toString('base64')
  const pages = await p.evaluate(async (pdfs) => {
    // Fake worker (main thread): the real worker file can't load from file://.
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = ''
    const out = []
    for (const [name, b64] of Object.entries(pdfs)) {
      const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
      const doc = await window.pdfjsLib.getDocument({ data }).promise
      for (let i = 1; i <= doc.numPages; i++) {
        const pg = await doc.getPage(i)
        const vp = pg.getViewport({ scale: 1.4 })
        const cv = document.createElement('canvas')
        cv.width = vp.width; cv.height = vp.height
        await pg.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise
        out.push({ name: `${name}_p${i}`, dataUrl: cv.toDataURL('image/png').split(',')[1] })
      }
    }
    return out
  }, { single, multi })
  pages.forEach((pg) => {
    fs.writeFileSync(path.join(ROOT, `pdf_${pg.name}.png`), Buffer.from(pg.dataUrl, 'base64'))
    console.log('wrote', pg.name)
  })
  await b.close()
}
main().catch((e) => { console.error('FAILED:', e.message); process.exit(1) })
