import type { Metadata } from "next";
import { SafetyScreen } from "@/features/safety/safety-screen";

export const metadata: Metadata = { title: "Safety Center" };

export default function Page() {
  return <SafetyScreen />;
}
