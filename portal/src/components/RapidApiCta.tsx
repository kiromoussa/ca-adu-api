import { getRapidApiUrl } from "@/lib/constants";

interface RapidApiCtaProps {
  label?: string;
  variant?: "primary" | "secondary";
  className?: string;
}

export default function RapidApiCta({
  label = "Get an API key",
  variant = "primary",
  className = "",
}: RapidApiCtaProps) {
  const href = getRapidApiUrl();
  const base =
    "inline-flex cursor-pointer items-center justify-center gap-2 rounded-card px-5 py-2.5 text-sm font-semibold transition-transform duration-150 hover:-translate-y-px";
  const styles =
    variant === "primary"
      ? "bg-accent text-white hover:bg-accent-deep"
      : "border border-line-strong text-ink hover:border-accent hover:text-accent-deep";

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${base} ${styles} ${className}`}
    >
      {label}
      <span aria-hidden="true" className="font-mono">
        -&gt;
      </span>
    </a>
  );
}
