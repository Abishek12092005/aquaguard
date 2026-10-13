const t = require('fs').readFileSync('frontend/dist-qa/qa-pdf-entry.js', 'utf8')
console.log('has 0.05 opacity:', t.includes('.05'))
console.log('has addPage:', t.includes('addPage'))
console.log('has watermark fn:', t.toLowerCase().includes('watermark') || t.includes('108') || t.includes('105'))
