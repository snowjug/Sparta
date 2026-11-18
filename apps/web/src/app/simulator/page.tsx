import type { Metadata } from "next";
import { LabLoader } from "@/features/lab/lab-loader";

export const metadata: Metadata = { title: "Simulator Lab" };

export default function Page() {
  return <LabLoader />;
}
