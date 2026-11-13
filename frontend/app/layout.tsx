import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import HealthBadge from "@/components/HealthBadge";

export const metadata: Metadata = {
  title: "TrustLens",
  description: "Every AI sentence backed by data you can click through to.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link href="/" className="brand">
            Trust<span>Lens</span>
          </Link>
          <nav>
            <Link href="/">Patients</Link>
            <Link href="/review">Review queue</Link>
            <Link href="/research">Researcher</Link>
            <Link href="/audit">Audit</Link>
          </nav>
          <div className="right">
            <HealthBadge />
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
