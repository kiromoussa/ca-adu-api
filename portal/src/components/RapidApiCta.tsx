import { getRapidApiUrl } from "@/lib/constants";

interface RapidApiCtaProps {
  label?: string;
  variant?: "primary" | "secondary";
  className?: string;
}

export default function RapidApiCta({
  label = "Get API key on RapidAPI",
  variant = "primary",
  className = "",
}: RapidApiCtaProps) {
  const href = getRapidApiUrl();
  const base =
    "inline-flex cursor-pointer items-center justify-center gap-2 rounded-md px-5 py-2.5 text-sm font-medium transition-colors";
  const styles =
    variant === "primary"
      ? "bg-ink text-white hover:bg-ink/85 dark:bg-white dark:text-ink dark:hover:bg-white/85"
      : "border border-ink/15 text-ink hover:bg-ink/5 dark:border-white/20 dark:text-ink-dark dark:hover:bg-white/10";

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${base} ${styles} ${className}`}
    >
      {label}
      <span aria-hidden="true">-&gt;</span>
    </a>
  );
}
