import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { Icon, type IconName } from "./icon";
import { Spinner } from "./spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface StyleOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-ink hover:brightness-110 border border-transparent",
  secondary: "border border-line-strong bg-surface text-fg hover:bg-raised",
  ghost: "border border-transparent text-fg hover:bg-raised",
  danger: "border border-danger/50 bg-danger-bg text-danger hover:brightness-110",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "min-h-11 px-4 text-sm",
  md: "min-h-11 px-5 text-sm",
  lg: "min-h-12 px-6 text-base",
};

/** Every button keeps a >= 44px touch target. */
export function buttonClasses({ variant = "secondary", size = "md", fullWidth }: StyleOptions = {}): string {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold select-none",
    "transition-[background-color,border-color,color,filter,transform] duration-150 active:scale-[0.98]",
    "disabled:cursor-not-allowed disabled:opacity-55 disabled:active:scale-100 aria-disabled:cursor-not-allowed aria-disabled:opacity-55",
    VARIANTS[variant],
    SIZES[size],
    fullWidth && "w-full",
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, StyleOptions {
  icon?: IconName;
  trailingIcon?: IconName;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, fullWidth, icon, trailingIcon, loading = false, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(buttonClasses({ variant, size, fullWidth }), className)}
      {...rest}
    >
      {loading ? <Spinner size={16} /> : icon ? <Icon name={icon} size={18} /> : null}
      {children}
      {trailingIcon && !loading ? <Icon name={trailingIcon} size={18} /> : null}
    </button>
  );
});

export interface LinkButtonProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">, StyleOptions {
  href: string;
  icon?: IconName;
  trailingIcon?: IconName;
  external?: boolean;
}

export function LinkButton({ href, variant, size, fullWidth, icon, trailingIcon, external, className, children, ...rest }: LinkButtonProps) {
  const classes = cn(buttonClasses({ variant, size, fullWidth }), className);
  const content = (
    <>
      {icon ? <Icon name={icon} size={18} /> : null}
      {children}
      {trailingIcon ? <Icon name={trailingIcon} size={18} /> : null}
    </>
  );
  if (external) {
    return (
      <a href={href} className={classes} target="_blank" rel="noopener noreferrer" {...rest}>
        {content}
      </a>
    );
  }
  return (
    <Link href={href} className={classes} {...rest}>
      {content}
    </Link>
  );
}

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> {
  icon: IconName;
  label: string;
  variant?: "secondary" | "ghost";
}

/** Icon-only control: the visible glyph is decorative, `label` is the accessible name. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, variant = "ghost", className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-11 shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:opacity-55",
        variant === "ghost" ? "text-fg hover:bg-raised" : "border border-line-strong bg-surface text-fg hover:bg-raised",
        className,
      )}
      {...rest}
    >
      <Icon name={icon} size={20} />
    </button>
  );
});
