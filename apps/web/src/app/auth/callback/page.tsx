import type { Metadata } from "next";
import { CallbackScreen } from "@/features/auth/callback-screen";

export const metadata: Metadata = { title: "Signing in" };

export default function AuthCallbackPage() {
  return <CallbackScreen />;
}
