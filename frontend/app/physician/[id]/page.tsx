"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import SummaryView from "@/components/SummaryView";

export default function PhysicianPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <h1>Patient summary (physician)</h1>
      <p className="sub">
        Codes, critic and verifier results per sentence. The AI summarises; it does not recommend. Flagged sentences go to the{" "}
        <Link href="/review">review queue</Link>. <Link href={`/patient/${id}`}>Patient view</Link>
      </p>
      <SummaryView patientId={id} audience="physician" />
    </>
  );
}
