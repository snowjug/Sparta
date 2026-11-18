import type { Metadata } from "next";
import { LiveIndexScreen } from "@/features/live/live-index-screen";

export const metadata: Metadata = { title: "Live call" };

export default function Page() {
  return <LiveIndexScreen />;
}
