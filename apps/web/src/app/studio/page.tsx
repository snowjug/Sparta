import type { Metadata } from "next";
import { StudioScreen } from "@/features/studio/studio-screen";

export const metadata: Metadata = { title: "Assistant Studio" };

export default function Page() {
  return <StudioScreen />;
}
