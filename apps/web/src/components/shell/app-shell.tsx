"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { describeError, isApiError } from "@/lib/api/errors";
import { getApiBaseUrl } from "@/lib/api/config";
import { readStorage, STORAGE_KEYS } from "@/lib/storage";
import { usePreferences, useSystemStatus } from "@/lib/query/hooks";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { AuthGate } from "./auth-gate";
import { DevBanner } from "./dev-banner";
import { BottomNav, SideNav, TopBar } from "./nav";

function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-full focus:bg-accent focus:px-5 focus:py-3 focus:text-sm focus:font-semibold focus:text-accent-ink"
    >
      Skip to main content
    </a>
  );
}

/** First visit: send owners who have not finished setup to onboarding (unless they chose "Skip for now"). */
function OnboardingGate() {
  const pathname = usePathname();
  const router = useRouter();
  const { data } = usePreferences();
  const needsOnboarding = data ? !data.onboarding_completed : false;

  useEffect(() => {
    if (!needsOnboarding || pathname.startsWith("/onboarding")) return;
    if (readStorage(STORAGE_KEYS.onboardingSkipped, "session") === "1") return;
    router.replace("/onboarding");
  }, [needsOnboarding, pathname, router]);

  return null;
}

function ApiOfflineNotice() {
  const { error, refetch, isFetching } = useSystemStatus();
  // Not being signed in is the sign-in gate's business, not "the API is offline".
  if (!error || (isApiError(error) && error.kind === "unauthorized")) return null;
  const described = describeError(error);
  return (
    <div role="alert" className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-danger/40 bg-danger-bg px-4 py-3 text-sm sm:mx-6 lg:mx-10">
      <Icon name="alert" size={20} className="shrink-0 text-danger" />
      <p className="min-w-0 flex-1 text-fg">
        <strong className="font-semibold">Can&apos;t reach the Sparta API.</strong> {described.message || `Expected it at ${getApiBaseUrl()}.`}
      </p>
      <Button variant="secondary" size="sm" icon="refresh" loading={isFetching} onClick={() => void refetch()}>
        Retry
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const focusMode = pathname.startsWith("/onboarding");
  return (
    <>
      <SkipLink />
      <DevBanner />
      <div className="mx-auto flex min-h-dvh w-full max-w-[1400px]">
        {focusMode ? null : <SideNav />}
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar minimal={focusMode} />
          <ApiOfflineNotice />
          <main id="main" tabIndex={-1} className="flex-1 px-4 pb-28 pt-5 outline-none sm:px-6 lg:px-10 lg:pb-14 lg:pt-8">
            <AuthGate>{children}</AuthGate>
          </main>
        </div>
      </div>
      {focusMode ? null : <BottomNav />}
      <OnboardingGate />
    </>
  );
}
