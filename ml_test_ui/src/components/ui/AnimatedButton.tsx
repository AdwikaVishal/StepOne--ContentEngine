"use client";

import { motion, type Variants } from "framer-motion";
import * as React from "react";

import { cn } from "../../lib/utils";

// Animation variants for different interactions
const buttonVariants: Variants = {
  initial: {
    scale: 1,
    rotateX: 0,
  },
  hover: {
    scale: 1.02,
    rotateX: -2,
    transition: {
      type: "spring",
      stiffness: 400,
      damping: 10,
    },
  },
  tap: {
    scale: 0.98,
    rotateX: 2,
    transition: {
      type: "spring",
      stiffness: 400,
      damping: 10,
    },
  },
};

const shimmerVariants: Variants = {
  initial: {
    x: "-100%",
  },
  animate: {
    x: "100%",
    transition: {
      duration: 1.5,
      ease: "easeInOut",
      repeat: Infinity,
      repeatDelay: 3,
    },
  },
};

const pulseVariants: Variants = {
  pulse: {
    boxShadow: [
      "0 0 0 0 hsl(var(--primary) / 0.4)",
      "0 0 0 20px hsl(var(--primary) / 0)",
    ],
    transition: {
      duration: 1.5,
      repeat: Infinity,
    },
  },
};

// Button sizes map to the project's design tokens (index.css).
const sizeMap: Record<string, { height: number; padding: string; fontSize: number; gap: number }> = {
  sm: { height: 32, padding: "0 10px", fontSize: 12, gap: 6 },
  md: { height: 40, padding: "0 16px", fontSize: 14, gap: 8 },
  lg: { height: 48, padding: "0 20px", fontSize: 16, gap: 10 },
};

const baseStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: "var(--rs)",
  fontWeight: 600,
  whiteSpace: "nowrap",
  position: "relative",
  overflow: "hidden",
  willChange: "transform",
};

export interface AnimatedButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>,
    | "onDrag"
    | "onDragStart"
    | "onDragEnd"
    | "onAnimationStart"
    | "onAnimationEnd"
    | "onAnimationIteration"> {
  /**
   * Accessible name for the control. Optional: when omitted the visible
   * children (or `iconLeft` + text) provide the accessible name.
   */
  label?: string;
  iconLeft?: React.ReactNode;
  iconRight?: React.ReactNode;
  loading?: boolean;
  variant?: "default" | "ghost" | "outline" | "gradient" | "danger";
  size?: "sm" | "md" | "lg";
  className?: string;
  onClick?: () => void;
}

const AnimatedButton = React.forwardRef<HTMLButtonElement, AnimatedButtonProps>(
  (
    {
      label,
      children,
      variant = "default",
      size = "md",
      iconLeft,
      iconRight,
      loading = false,
      className,
      style,
      onClick,
      disabled,
      ...props
    },
    ref
  ) => {
    const [isHovered, setIsHovered] = React.useState(false);
    const [ripples, setRipples] = React.useState<
      Array<{ id: number; x: number; y: number }>
    >([]);

    const s = sizeMap[size];
    const isDisabled = loading || disabled;
    // Children (icon + text nodes) are the visible content when provided;
    // `label` only supplies the accessible name / tooltip text.
    const hasChildren = children !== undefined && children !== null && children !== false && children !== "";

    const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
      if (loading || disabled) return;

      // Create ripple effect
      const rect = event.currentTarget.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const newRipple = { id: Date.now(), x, y };

      setRipples((prev) => [...prev, newRipple]);

      // Remove ripple after animation
      setTimeout(() => {
        setRipples((prev) => prev.filter((ripple) => ripple.id !== newRipple.id));
      }, 600);

      onClick?.();
    };

    const inlineStyle: React.CSSProperties = {
      ...baseStyle,
      height: s.height,
      padding: s.padding,
      fontSize: s.fontSize,
      gap: s.gap,
      cursor: isDisabled ? "not-allowed" : "pointer",
      opacity: isDisabled ? 0.5 : 1,
      // Disabled removes the shadow; variant base shadow lives in CSS classes
      // so :hover overrides apply correctly.
      boxShadow: isDisabled ? "none" : undefined,
      ...style,
    };

    return (
      <motion.button
        ref={ref}
        data-variant={variant}
        className={cn("ce-animated-button", `ce-btn--${variant}`, className)}
        style={inlineStyle}
        variants={buttonVariants}
        initial="initial"
        whileHover={!isDisabled ? "hover" : "initial"}
        whileTap={!isDisabled ? "tap" : "initial"}
        onHoverStart={() => setIsHovered(true)}
        onHoverEnd={() => setIsHovered(false)}
        onClick={handleClick}
        disabled={isDisabled}
        aria-label={label?.trim() || undefined}
        aria-busy={loading}
        {...props}
      >
        {/* Shimmer effect for gradient variant */}
        {variant === "gradient" && (
          <motion.div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent)",
            }}
            variants={shimmerVariants}
            initial="initial"
            animate={isHovered ? "animate" : "initial"}
          />
        )}

        {/* Magnetic glow effect on hover */}
        {isHovered && variant !== "ghost" && variant !== "outline" && (
          <motion.div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "inherit",
              background:
                "linear-gradient(135deg, rgba(124,106,255,0.2), rgba(124,106,255,0.25), rgba(124,106,255,0.15))",
              filter: "blur(12px)",
            }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1.1 }}
            transition={{ duration: 0.3 }}
          />
        )}

        {/* Content wrapper */}
        <span
          style={{
            position: "relative",
            zIndex: 10,
            display: "flex",
            alignItems: "center",
            gap: s.gap,
          }}
        >
          {/* Loading spinner (replaces the left icon) */}
          {loading && (
            <motion.svg
              style={{
                animation: "spin 1s linear infinite",
                width: 16,
                height: 16,
                flexShrink: 0,
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2 }}
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M12 4.75V6.25"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M17.25 12H18.75"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M12 17.25V18.75"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M5.25 12H6.75"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M7.5 7.5L8.56 8.56"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M15.44 15.44L16.5 16.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M16.5 7.5L15.44 8.56"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M8.56 15.44L7.5 16.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </motion.svg>
          )}

          {hasChildren ? (
            /* Callers render their own icon + text through children */
            <motion.span
              initial={{ y: 1, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ duration: 0.2, delay: 0.05 }}
              style={{ display: "inline-flex", alignItems: "center", gap: s.gap }}
            >
              {children}
            </motion.span>
          ) : (
            <>
              {!loading && iconLeft && (
                <motion.span
                  initial={{ x: -2, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  transition={{ duration: 0.2, delay: 0.1 }}
                  style={{ pointerEvents: "none", flexShrink: 0 }}
                >
                  {iconLeft}
                </motion.span>
              )}

              {/* Button label */}
              <motion.span
                initial={{ y: 1, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.2, delay: 0.05 }}
              >
                {label}
              </motion.span>

              {/* Right icon */}
              {!loading && iconRight && (
                <motion.span
                  initial={{ x: 2, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  transition={{ duration: 0.2, delay: 0.15 }}
                  style={{ pointerEvents: "none", flexShrink: 0 }}
                >
                  {iconRight}
                </motion.span>
              )}
            </>
          )}
        </span>

        {/* Ripple effects */}
        {ripples.map((ripple) => (
          <motion.span
            key={ripple.id}
            style={{
              position: "absolute",
              borderRadius: "50%",
              background: "rgba(255,255,255,0.2)",
              pointerEvents: "none",
              left: ripple.x,
              top: ripple.y,
            }}
            initial={{
              width: 0,
              height: 0,
              x: "-50%",
              y: "-50%",
              opacity: 1,
            }}
            animate={{
              width: 120,
              height: 120,
              opacity: 0,
            }}
            transition={{
              duration: 0.6,
              ease: "easeOut",
            }}
          />
        ))}
      </motion.button>
    );
  }
);

AnimatedButton.displayName = "AnimatedButton";

export { AnimatedButton };
export { shimmerVariants, pulseVariants, buttonVariants };
