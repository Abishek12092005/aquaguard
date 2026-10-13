const path = require('path')
const EXT = 'C:/Users/abishek/.vscode/extensions/danielsanmedium.dscodegpt-3.24.76/standalone/node_modules'
const { chromium } = require(path.join(EXT, 'patchright'))
const fs = require('fs')
const http = require('http')

const DIST = 'C:/Users/abishek/OneDrive/Desktop/aquagaurd/frontend/dist-qa'
const MIME = { '.js': 'text/javascript', '.html': 'text/html' }

// Tiny static server for the QA bundle so its relative asset imports resolve.
const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0]
  const file = path.join(DIST, url === '/' ? 'index.html' : url)
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end(); return }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' })
    res.end(data)
  })
}).listen(4599)

const ROW = {
  id: 42,
  created_at: new Date().toISOString(),
  prediction: 'unsafe',
  confidence: 0.913,
  model_version: 'rf-v3.2',
  location_name: 'Borewell 7, Kolar Main Road',
  location_district: 'Kolar',
  location_state: 'Karnataka',
  location_country: 'India',
  location_pincode: '563101',
  water_source_type: 'Borewell',
  water_source_name: 'Community Borewell 7',
  ph: 5.2,
  turbidity: 8.4,
  tds: 980,
  hardness: 420,
  conductivity: 1150,
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  page.on('console', (m) => { if (m.type() === 'error') console.log('ERR:', m.text()) })
  page.on('pageerror', (e) => console.log('PAGEERR:', e.message))
  page.on('response', (r) => console.log('RESP:', r.status(), r.url()))
  await page.goto('http://localhost:4599/blank.html', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => import('/qa-pdf-entry.js'))
  console.log('loaded type:', await page.evaluate(() => String(typeof window.__qaPdf)))
  console.log('scripts:', await page.evaluate(() => [...document.scripts].map(s => s.src || s.textContent.slice(0, 40))))
  const bytes = await page.evaluate(async (row) => {
    const b = await window.__qaPdf([row], { title: 'Single reading report', output: 'blob' })
    return Array.from(new Uint8Array(await b.arrayBuffer()))
  }, ROW)
  fs.writeFileSync('C:/Users/abishek/OneDrive/Desktop/aquagaurd/qa_report.pdf', Buffer.from(bytes))
  console.log('PDF bytes:', bytes.length, 'header:', String.fromCharCode(...bytes.slice(0, 5)))
  const bytesMulti = await page.evaluate(async (row) => {
    const b = await window.__qaPdf([row, { ...row, id: 43, prediction: 'safe', confidence: 0.77 }], { title: 'All readings', output: 'blob' })
    return Array.from(new Uint8Array(await b.arrayBuffer()))
  }, ROW)
  fs.writeFileSync('C:/Users/abishek/OneDrive/Desktop/aquagaurd/qa_report_multi.pdf', Buffer.from(bytesMulti))
  console.log('multi PDF bytes:', bytesMulti.length)
  await browser.close()
  server.close()
}
main().catch((e) => { console.error('FAILED:', e.message); server.close(); process.exit(1) })
