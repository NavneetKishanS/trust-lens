// Small inline SVG icon set (Lucide-style strokes, 24×24 grid). Replaces unicode glyphs, which render
// inconsistently across platforms (some as colour emoji). Decorative by default: aria-hidden.
export type IconName =
  | "overview" | "graph" | "search" | "cohort" | "review" | "shield" | "users"
  | "check" | "alert" | "x" | "info" | "circle" | "diamond" | "menu" | "arrow-right" | "external";

const PATHS: Record<IconName, React.ReactNode> = {
  overview: (<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>),
  graph: (<><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="8" r="2.5" /><circle cx="9" cy="18" r="2.5" /><path d="M8.3 7l7.4.6M7 8.3l1.4 7.3M16.4 10l-5.6 6.2" /></>),
  search: (<><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></>),
  cohort: (<><path d="M3 3v18h18" /><rect x="7" y="12" width="3" height="5" rx="0.5" /><rect x="12" y="8" width="3" height="9" rx="0.5" /><rect x="17" y="5" width="3" height="12" rx="0.5" /></>),
  review: (<><path d="M9 11l3 3 8-8" /><path d="M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9" /></>),
  shield: (<><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" /><path d="M9 12l2 2 4-4" /></>),
  users: (<><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.4 3.3-5.5 6.5-5.5s5.9 2.1 6.5 5.5" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.6.8 2.7 2.6 3 5.2" /></>),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  alert: (<><path d="M10.3 3.9L2.4 17.6A2 2 0 0 0 4.1 20.6h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4.5M12 17h.01" /></>),
  x: <path d="M6 6l12 12M18 6L6 18" />,
  info: (<><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.5h.01" /></>),
  circle: <circle cx="12" cy="12" r="8" />,
  diamond: <path d="M12 3l9 9-9 9-9-9 9-9z" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  "arrow-right": <path d="M5 12h14M13 6l6 6-6 6" />,
  external: (<><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></>),
};

export default function Icon({ name, size = 16, strokeWidth = 2, className, label }: { name: IconName; size?: number; strokeWidth?: number; className?: string; label?: string }) {
  return (
    <svg
      className={`icon ${className ?? ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
