import * as React from "react"
import { AnimatedButton } from "./AnimatedButton"

export type AnimatedBtnProps = Omit<
  React.ComponentProps<typeof AnimatedButton>,
  "label"
> & {
  children: React.ReactNode
  loading?: boolean
  label?: string
}

// Adapter: keeps existing Btn usage style (children) while animating.
// We only use `label` for aria-label and visible text; children are treated as the label text when possible.
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

  const resolvedLabel = (label ?? rawText).trim() || "Animated button"

  return (
    <AnimatedButton
      {...(props as any)}
      label={resolvedLabel}
      variant={variant}
      size={size}
      className={className}
      loading={loading}
      disabled={disabled}
    />
  )
}



