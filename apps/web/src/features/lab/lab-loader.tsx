"use client";

import dynamic from "next/dynamic";
import { LoadingBlock } from "@/components/ui/feedback";

/** The Simulator Lab is the heaviest screen (microphone, replay, event log): it is split out and loaded on demand. */
const LabScreen = dynamic(() => import("./lab-screen"), {
  ssr: false,
  loading: () => <LoadingBlock label="Loading the Simulator Lab" lines={6} />,
});

export function LabLoader() {
  return <LabScreen />;
}
