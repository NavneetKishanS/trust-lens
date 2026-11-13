// Single source for navigation, page titles and breadcrumbs.
export type NavItem = { href: string; label: string; icon: string; group: "Research" | "Governance" | "Clinical views" };

export const NAV: NavItem[] = [
  { href: "/", label: "Research Overview", icon: "◎", group: "Research" },
  { href: "/graph", label: "Knowledge Graph", icon: "⬡", group: "Research" },
  { href: "/ask", label: "Ask the Data", icon: "⌕", group: "Research" },
  { href: "/cohorts", label: "Cohort Explorer", icon: "▦", group: "Research" },
  { href: "/review", label: "Clinical Review", icon: "✓", group: "Governance" },
  { href: "/audit", label: "Trust & Audit", icon: "⛨", group: "Governance" },
  { href: "/patients", label: "Patient & physician", icon: "☰", group: "Clinical views" },
];

export function crumbsFor(path: string): { section: string; page: string } {
  if (path.startsWith("/patient/")) return { section: "Clinical views", page: "Patient view" };
  if (path.startsWith("/physician/")) return { section: "Clinical views", page: "Physician view" };
  const item = NAV.find((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href)));
  return item ? { section: item.group, page: item.label } : { section: "Research", page: "" };
}

export function isActive(href: string, path: string): boolean {
  if (href === "/") return path === "/";
  if (href === "/patients") return path.startsWith("/patient") || path.startsWith("/physician");
  return path.startsWith(href);
}
