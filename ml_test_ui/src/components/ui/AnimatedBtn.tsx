import * as React from "react"
import { AnimatedButton } from "./AnimatedButton"

export type AnimatedBtnProps = Omit<
  React.ComponentProps<typeof AnimatedButton>,
  "label"
> & {
  children?: React.ReactNode
  loading?: boolean
  label?: string
}

// Adapter: keeps the existing children-based usage style (icon + text nodes)
// while delegating rendering to AnimatedButton.
//
// - `children` are rendered as the visible button content (icons included).
// - `label` is the accessible name; when it is omitted we derive it from the
//   string children so icon-only buttons still need an explicit label but
//   text buttons never show a placeholder.
export function AnimatedBtn({
  children,
  loading,
  variant,
  size,
  className,
  disabled,
  label,
  ...props
}: AnimatedBtnProps) {
  const rawText = React.Children.toArray(children)
    .map((c) => (typeof c === "string" ? c : ""))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()

  // Never ship a placeholder label: explicit `label` wins, otherwise the
  // visible text, otherwise undefined (icon-only callers must pass `label`).
  const resolvedLabel = label?.trim() || rawText || undefined

  return (
    <AnimatedButton
      {...(props as any)}
      label={resolvedLabel}
      variant={variant}
      size={size}
      className={className}
      loading={loading}
      disabled={disabled}
    >
      {children}
    </AnimatedButton>
  )
}
