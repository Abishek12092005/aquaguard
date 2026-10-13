const { chromium } = require('C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules/patchright')
const fs = require('fs')
const path = require('path')
const http = require('http')
const ROOT = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'
const MIME = { '.js': 'text/javascript', '.html': 'text/html' }

// HTTP host: classic scripts execute on http origins, and the worker can load
// from the same origin — the setup that never worked before was MIME/404s.
const s = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]).replace(/^\//, '') || 'pdf_render_host3.html'
  const f = path.join(ROOT, rel)
  fs.readFile(f, (e, d) => {
    if (e) { console.log('404', rel); r.writeHead(404); r.end(); return }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' })
    r.end(d)
  })
})
s.listen(4620, async () => {
  const b = await chromium.launch()
  const p = await b.newPage()
  p.on('pageerror', (e) => console.log('PE:', e.message.slice(0, 300)))
  p.on('console', (m) => console.log('C:', m.type(), m.text().slice(0, 200)))
  await p.goto('http://localhost:4620/pdf_render_host3.html', { waitUntil: 'load' })
  // Point the worker at the real worker file on the same origin.
  await p.addScriptTag({ content: 'window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/package/build/pdf.worker.min.js"' })
  const single = fs.readFileSync(path.join(ROOT, 'qa_report.pdf')).toString('base64')
  const multi = fs.readFileSync(path.join(ROOT, 'qa_report_multi.pdf')).toString('base64')
  await p.addScriptTag({ content: `window.__render(${JSON.stringify(single)}, ${JSON.stringify(multi)}).then(() => { document.title = 'RENDER_DONE' }).catch(e => { document.title = 'RENDER_ERR ' + e.message })` })
  for (let i = 0; i < 30; i++) {
    await p.waitForTimeout(2000)
    const t = await p.title()
    console.log('poll', i, t)
    if (t.startsWith('RENDER')) break
  }
  const out = await p.evaluate(() => (document.getElementById('out') || {}).value || '')
  console.log('out len:', out.length)
  if (out) {
    JSON.parse(out).forEach((pg) => {
      fs.writeFileSync(path.join(ROOT, `pdf_${pg.name}.png`), Buffer.from(pg.dataUrl, 'base64'))
      console.log('wrote', pg.name)
    })
  }
  await b.close()
  s.close()
})
