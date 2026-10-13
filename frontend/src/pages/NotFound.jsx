import { Link } from 'react-router-dom'

import Button from '@/components/Button'
import { ROUTES } from '@/utils/constants'

/** 404 fallback for unknown routes. */
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-4 text-center dark:bg-slate-950">
      <p className="text-5xl font-semibold tracking-tight text-aqua-600">404</p>
      <h1 className="text-lg font-semibold text-slate-900">This page does not exist</h1>
      <p className="max-w-sm text-sm text-slate-500">
        The page you are looking for may have been moved or removed.
      </p>
      <Link to={ROUTES.home} className="mt-2">
        <Button variant="secondary">Back to Home</Button>
      </Link>
    </div>
  )
}
