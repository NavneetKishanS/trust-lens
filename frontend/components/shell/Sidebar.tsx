"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import Icon from "@/components/Icon";
import { NAV, isActive } from "./nav";

export default function Sidebar() {
  const path = usePathname() ?? "/";
  const groups = ["Research", "Governance", "Clinical views"] as const;
  // Below 960px the nav collapses behind a menu button; close it whenever the route changes.
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(path);
  if (openedAt !== path) {
    setOpenedAt(path);
    setOpen(false);
  }

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand">
        <Link href="/" className="brand-link">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="6.5" />
              <path d="M8.5 11.2l1.8 1.8 3.4-3.6M16 16l4 4" />
            </svg>
          </span>
          <span>
            <span className="name">
              Trust<span>Lens</span>
            </span>
            <span className="product">Research Studio</span>
          </span>
        </Link>
        <button
          type="button"
          className="menu-toggle"
          aria-expanded={open}
          aria-controls="primary-nav"
          aria-label={open ? "Close navigation" : "Open navigation"}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name={open ? "x" : "menu"} size={18} />
        </button>
      </div>
      <div id="primary-nav" className="nav-wrap">
        <p className="tagline">Evidence-backed clinical research intelligence.</p>
        {groups.map((g) => (
          <nav className="nav-group" key={g} aria-label={g}>
            <div className="label">{g}</div>
            {NAV.filter((n) => n.group === g).map((n) => {
              const active = isActive(n.href, path);
              return (
                <Link key={n.href} href={n.href} className={`nav-link ${active ? "active" : ""}`} aria-current={active ? "page" : undefined}>
                  <Icon name={n.icon} size={16} className="ico" />
                  {n.label}
                </Link>
              );
            })}
          </nav>
        ))}
        <div className="foot">
          Synthetic data only (Synthea + planted test signals). Papers from Europe PMC.
          <br />
          Exasol × Medical Valley EMN · Healthcare Hackathon Bayern 2026
        </div>
      </div>
    </aside>
  );
}
