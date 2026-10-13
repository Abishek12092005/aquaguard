// Test-only entry: exposes the real PDF generator on window for QA.
import { downloadReportsPdf } from './src/utils/reports'

window.__qaPdf = (rows, opts) => downloadReportsPdf(rows, opts)
