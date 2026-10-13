const VARIANTS = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
}

/** Two sizes only: the default, and a compact one for toolbars and table rows. */
const SIZES = {
  md: '',
  sm: 'px-2.5 py-1.5 text-xs',
  icon: 'h-9 w-9 p-0',
}

/** Accessible button with the project's variants and sizes. */
export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  type = 'button',
  loading = false,
  className = '',
  disabled,
  icon,
  ...rest
}) {
  return (
    <button
      type={type}
      className={`${VARIANTS[variant] || VARIANTS.primary} ${SIZES[size] || ''} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <span
          className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      ) : (
        icon
      )}
      {children}
    </button>
  )
}
