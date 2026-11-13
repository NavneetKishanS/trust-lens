import { redirect } from "next/navigation";

// The researcher workspace is now the home page (Research Overview).
export default function ResearchRedirect() {
  redirect("/");
}
