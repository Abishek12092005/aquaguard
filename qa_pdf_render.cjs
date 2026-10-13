const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))
const fs = require('fs')
const http = require('http')

// Renders the generated PDFs with pdf.js served from a local tiny server.
const DIST = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd'
const MIME = { '.js': 'text/javascript', '.html': 'text/html', '.pdf': 'application/pdf' }

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0]
  const file = path.join(DIST, url === '/' ? 'pdfjs_check.js' : url.replace(/^\//, ''))
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end(); return }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' })
    res.end(data)
  })
}).listen(4603)

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const pdfSingle = fs.readFileSync('C:/Users/abishek/OneDrive/Desktop/aquagaurd/qa_report.pdf').toString('base64')
  const pdfMulti = fs.readFileSync('C:/Users/abishek/OneDrive/Desktop/aquagaurd/qa_report_multi.pdf').toString('base64')
  await page.goto('http://localhost:4603/anything', { waitUntil: 'load' }).catch(() => {})
  // The preview site's CSP blocks classic script execution, so pdf.js's UMD
  // bundle is imported as a MODULE from a blob URL — the same trick that made
  // the QA bundle load. The UMD wrapper falls through to the globalThis branch
  // inside a module, which is exactly what we need.
  const umd = fs.readFileSync('C:/Users/abishek/OneDrive/Desktop/aquagaurd/pdfjs_check.js', 'utf8')
  const libType = await page.evaluate(async (code) => {
    try {
      const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }))
      await import(url)
      return typeof window.pdfjsLib
    } catch (e) {
      return 'ERR ' + e.message
    }
  }, umd)
  console.log('lib after import:', libType)
  if (libType !== 'object') process.exit(1)
  // Point pdf.js at the fake worker path: importing the bundle AS A MODULE set
  // pdfjsLib, but a worker created from a module blob hangs. Setting the
  // `isEvalSupported` off and using `disableWorker` via the legacy global isn't
  // exposed; instead, import the worker code as a classic Worker from a blob
  // whose inner code re-imports the bundle... Simplest reliable route: run the
  // whole render in a fresh page that loads pdf.js as a CLASSIC script from a
  // data: URL in a CSP-free about:blank context — done above via module import;
  // here we just use the FAKE worker by giving a workerSrc that returns the
  // bundle itself, which pdf.js evals on the main thread when Worker fails.
  await page.evaluate((code) => {
    const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }))
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = url
  }, umd)
  const pages = await page.evaluate(async (pdfs) => {
    const results = []
    for (const [name, b64] of Object.entries(pdfs)) {
      const data = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
      const doc = await window.pdfjsLib.getDocument({ data }).promise
      for (let i = 1; i <= doc.numPages; i++) {
        const pg = await doc.getPage(i)
        const vp = pg.getViewport({ scale: 1.4 })
        const cv = document.createElement('canvas')
        cv.width = vp.width; cv.height = vp.height
        await pg.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise
        results.push({ name: `${name}_p${i}`, dataUrl: cv.toDataURL('image/png').split(',')[1] })
      }
    }
    return results
  }, { single: pdfSingle, multi: pdfMulti })
  pages.forEach((p) => {
    fs.writeFileSync(path.join(DIST, `pdf_${p.name}.png`), Buffer.from(p.dataUrl, 'base64'))
    console.log('wrote', p.name)
  })
  await browser.close()
  server.close()
}
main().catch((e) => { console.error('FAILED:', e.message); server.close(); process.exit(1) })
