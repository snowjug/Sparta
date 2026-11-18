import type { Metadata } from "next";
import { Suspense } from "react";
import { LoadingBlock } from "@/components/ui/feedback";
import { HistoryScreen } from "@/features/history/history-screen";

export const metadata: Metadata = { title: "Call history" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock label="Loading call history" lines={5} />}>
      <HistoryScreen />
    </Suspense>
  );
}
