import type { Metadata } from "next";
import { CallDetailScreen } from "@/features/call-detail/call-detail-screen";

export const metadata: Metadata = { title: "Call detail" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CallDetailScreen callId={id} />;
}
