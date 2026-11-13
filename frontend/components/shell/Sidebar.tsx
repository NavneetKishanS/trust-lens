"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV, isActive } from "./nav";

export default function Sidebar() {
  const path = usePathname() ?? "/";
  const groups = ["Research", "Governance", "Clinical views"] as const;
  return (
    <aside className="sidebar">
      <div className="brand">
        <Link href="/">
          <div className="name">
            Trust<span>Lens</span>
          </div>
          <div className="product">Research Studio</div>
        </Link>
        <div className="tagline">Evidence-backed clinical research intelligence.</div>
      </div>
      {groups.map((g) => (
        <nav className="nav-group" key={g} aria-label={g}>
          <div className="label">{g}</div>
          {NAV.filter((n) => n.group === g).map((n) => (
            <Link key={n.href} href={n.href} className={`nav-link ${isActive(n.href, path) ? "active" : ""}`}>
              <span className="ico" aria-hidden>
                {n.icon}
              </span>
              {n.label}
            </Link>
          ))}
        </nav>
      ))}
      <div className="foot">
        Synthetic data only (Synthea + planted test signals). Papers from Europe PMC.
        <br />
        Exasol × Medical Valley EMN · Healthcare Hackathon Bayern 2026
      </div>
    </aside>
  );
}
