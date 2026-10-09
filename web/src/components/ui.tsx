import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

// Small, composable shadcn-style primitives; semantic HTML and class variants.
export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "secondary" | "ghost" | "accent";
}) {
  return (
    <button className={`button button-${variant} ${className}`} {...props} />
  );
}
export function Card({
  className = "",
  ...props
}: HTMLAttributes<HTMLElement>) {
  return <section className={`card ${className}`} {...props} />;
}
export function Badge({
  children,
  tone = "muted",
  className = "",
}: {
  children: ReactNode;
  tone?: "muted" | "positive" | "negative" | "accent";
  className?: string;
}) {
  return <span className={`badge badge-${tone} ${className}`}>{children}</span>;
}
export function CardHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card-heading">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function ScoreBar({ value, label }: { value: number; label: string }) {
  return (
    <div
      className="score-bar"
      role="meter"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span style={{ width: `${value}%` }} />
    </div>
  );
}
