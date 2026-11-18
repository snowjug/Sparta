import type { Metadata } from "next";
import { LiveCallScreen } from "@/features/live/live-call-screen";

export const metadata: Metadata = { title: "Live call" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <LiveCallScreen callId={id} />;
}
