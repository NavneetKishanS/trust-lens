"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import SummaryView from "@/components/SummaryView";
import SymptomReport from "@/components/SymptomReport";

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <h1>Your health overview</h1>
      <p className="sub">
        Written by AI from your records, and checked by other programs before you see it. Click any sentence to see where it comes
        from. This is not a diagnosis or medical advice. <Link href={`/physician/${id}`}>Physician view</Link>
      </p>
      <SummaryView patientId={id} audience="patient" />
      <SymptomReport patientId={id} />
    </>
  );
}
