/**
 * Stub for jsPDF's OPTIONAL integrations.
 *
 * WHY THIS FILE EXISTS. jsPDF can render SVG (`canvg`), sanitise HTML
 * (`dompurify`) and rasterise DOM nodes (`html2canvas`). All three are listed as
 * OPTIONAL dependencies: jsPDF imports them lazily, inside a try/catch, purely
 * so the `svg()`, `html()` and `addHtml()` methods work. This application calls
 * none of them — the report PDF is drawn with jsPDF's own text, line, shape and
 * table primitives.
 *
 * Without the packages installed, the dev server refuses to transform jsPDF's
 * bundle ("Failed to resolve import canvg"), and a production build needs them
 * marked external. Neither is acceptable: a dev server that will not start, and
 * a build whose correctness depends on a bundler flag.
 *
 * So the three specifiers are aliased here to this no-op module. The lazy
 * `import()` inside jsPDF still resolves, the feature it guards is simply never
 * reachable from any code path in this app, and nothing hundreds of KB is added
 * to the bundle for a capability that is not used.
 */
export default {}
export const Canvg = undefined
export const sanitize = (value) => value
export const html2canvas = undefined
