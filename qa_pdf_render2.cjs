const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const http = require('http')
const fs = require('fs')
const path = require('path')

// Serves the pdfjs-dist package and the generated PDFs; renders both PDFs to PNGs.
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'
const MIME = { '.js': 'text/javascript', '.html': 'text/html' }
const s = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]).replace(/^\//, '') || 'pdf_render_host.html'
  const f = path.join(ROOT, rel)
  fs.readFile(f, (e, d) => {
    if (e) { r.writeHead(404); r.end('nf'); return }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' })
    r.end(d)
  })
})
s.listen(4613, async () => {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 200)))
  fs.writeFileSync(path.join(ROOT, 'pdf_render_host.html'), '<!doctype html><html><body><script src="/package/build/pdf.min.js"></script></body></html>')
  await p.goto('http://localhost:4613/pdf_render_host.html', { waitUntil: 'load' })
  await p.waitForTimeout(2500)
  const t = await p.evaluate(() => typeof window.pdfjsLib)
  console.log('lib:', t)
  if (t !== 'object') { await b.close(); s.close(); process.exit(1) }
  const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')
  const multi = fs.readFileSync(path.join(ROOT, 'qa_report_multi.pdf')).toString('base64')
  const pages = await p.evaluate(async (pdfs) => {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = '/package/build/pdf.worker.min.js'
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
  s.close()
})
