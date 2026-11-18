import type { Metadata } from "next";
import { OnboardingScreen } from "@/features/onboarding/onboarding-screen";

export const metadata: Metadata = { title: "Set up Sparta" };

export default function Page() {
  return <OnboardingScreen />;
}
