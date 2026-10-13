/**
 * Shared UI primitives.
 *
 * Layout components (Navbar, Sidebar, AppLayout) and the Aqua AI panel live in
 * their own modules; this barrel exports the small reusable pieces used across
 * pages so imports stay short: `import { Card, Button } from '@/components'`.
 */

export { default as Button } from '@/components/Button'
export { default as Card } from '@/components/Card'
export { default as Badge } from '@/components/Badge'
export { default as Spinner } from '@/components/Spinner'
export { default as EmptyState } from '@/components/EmptyState'
export { default as ErrorState } from '@/components/ErrorState'
export { default as StatCard } from '@/components/StatCard'
export { default as Navbar } from '@/components/Navbar'
export { default as Sidebar } from '@/components/Sidebar'
export { default as AquaAIPanel } from '@/components/AquaAIPanel'
