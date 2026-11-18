"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { fieldErrors } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { AssistantProfile, UserPreferences } from "@/lib/api/types";
import { useAssistantProfile, usePreferences } from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { STORAGE_KEYS, writeStorage } from "@/lib/storage";
import { useCssVar } from "@/lib/use-css-var";
import { useStoredString } from "@/lib/use-stored";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Card } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import {
  DisclosureStep,
  LanguageStep,
  PrivacyStep,
  STEP_TITLES,
  StrictnessStep,
  TelephonyStep,
  TrustedStep,
  VoiceStep,
  WalkthroughStep,
  WelcomeStep,
  type StepProps,
} from "./steps";

const LAST = STEP_TITLES.length - 1;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function ProgressBar({ step }: { step: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useCssVar(ref, "--fill", (step + 1) / STEP_TITLES.length);
  return (
    <div
      role="progressbar"
      aria-label="Setup progress"
      aria-valuemin={1}
      aria-valuemax={STEP_TITLES.length}
      aria-valuenow={step + 1}
      aria-valuetext={`Step ${step + 1} of ${STEP_TITLES.length}: ${STEP_TITLES[step]}`}
      className="h-1.5 overflow-hidden rounded-full bg-sunken ring-1 ring-line"
    >
      <div ref={ref} className="sp-bar-fill h-full w-full rounded-full" />
    </div>
  );
}

export function OnboardingScreen() {
  const api = useApi();
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const prefsQuery = usePreferences();
  const profileQuery = useAssistantProfile();
  const [stepText, setStepText] = useStoredString(STORAGE_KEYS.onboardingStep, "0", "session");
  const step = Math.min(LAST, Math.max(0, Number.parseInt(stepText, 10) || 0));
  const [prefsDraft, setPrefsDraft] = useState<UserPreferences | null>(null);
  const [profileDraft, setProfileDraft] = useState<AssistantProfile | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const heading = useRef<HTMLHeadingElement>(null);

  // Move focus to the step title so screen-reader and keyboard users land on the new step.
  useEffect(() => {
    heading.current?.focus();
  }, [step]);

  const prefs = prefsDraft ?? prefsQuery.data;
  const profile = profileDraft ?? profileQuery.data;

  const save = useMutation({
    mutationFn: async ({ complete }: { complete: boolean }) => {
      const out: { prefs?: UserPreferences; profile?: AssistantProfile } = {};
      if (prefs && prefsQuery.data) {
        const next = complete ? { ...prefs, onboarding_completed: true } : prefs;
        if (!same(next, prefsQuery.data)) out.prefs = await api.preferences.put(next);
      }
      if (profile && profileQuery.data && !same(profile, profileQuery.data)) out.profile = await api.assistant.put(profile);
      return out;
    },
    onSuccess: (saved) => {
      if (saved.prefs) queryClient.setQueryData(qk.preferences, saved.prefs);
      if (saved.profile) queryClient.setQueryData(qk.assistant, saved.profile);
      void queryClient.invalidateQueries({ queryKey: ["assistant", "preview"] });
      void queryClient.invalidateQueries({ queryKey: qk.home });
      setPrefsDraft(null);
      setProfileDraft(null);
      setErrors({});
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });

  if (prefsQuery.isPending || profileQuery.isPending) return <LoadingBlock label="Loading setup" lines={5} />;
  if (prefsQuery.isError) return <ErrorState error={prefsQuery.error} onRetry={() => void prefsQuery.refetch()} title="Couldn't load your settings" />;
  if (profileQuery.isError) return <ErrorState error={profileQuery.error} onRetry={() => void profileQuery.refetch()} title="Couldn't load your assistant profile" />;
  if (!prefs || !profile) return null;

  const props: StepProps = { prefs, profile, setPrefs: setPrefsDraft, setProfile: setProfileDraft, errors };

  async function go(next: number) {
    try {
      await save.mutateAsync({ complete: false });
      setStepText(String(next));
    } catch {
      /* the failure is shown as a toast and inline field errors; stay on this step */
    }
  }

  async function finish() {
    try {
      await save.mutateAsync({ complete: true });
      writeStorage(STORAGE_KEYS.onboardingStep, null, "session");
      writeStorage(STORAGE_KEYS.onboardingSkipped, null, "session");
      toast.success("Sparta is ready. Try a simulated call from the Simulator Lab.", { title: "Setup complete" });
      router.push("/");
    } catch {
      /* shown as a toast */
    }
  }

  function skip() {
    writeStorage(STORAGE_KEYS.onboardingSkipped, "1", "session");
    router.push("/");
  }

  const body = [
    <WelcomeStep key="welcome" />,
    <DisclosureStep key="disclosure" {...props} />,
    <PrivacyStep key="privacy" {...props} />,
    <LanguageStep key="languages" {...props} />,
    <VoiceStep key="voice" {...props} />,
    <StrictnessStep key="strictness" {...props} />,
    <TrustedStep key="trusted" {...props} />,
    <WalkthroughStep key="walkthrough" />,
    <TelephonyStep key="telephony" />,
  ][step];

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6" data-testid="onboarding" data-step={step + 1}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold tabular-nums text-accent" data-testid="step-counter">
            Step {step + 1} of {STEP_TITLES.length}
          </p>
          <Button variant="ghost" size="sm" onClick={skip} data-testid="skip-onboarding">
            Skip for now
          </Button>
        </div>
        <ProgressBar step={step} />
      </div>

      <Card className="space-y-6">
        <h1 ref={heading} tabIndex={-1} className="text-balance text-2xl font-semibold tracking-tight text-fg outline-none sm:text-3xl" data-testid="step-title">
          {STEP_TITLES[step]}
        </h1>
        {body}
      </Card>

      <div className="flex items-center justify-between gap-3">
        <Button variant="secondary" icon="arrow-left" disabled={step === 0 || save.isPending} onClick={() => void go(step - 1)}>
          Back
        </Button>
        {step < LAST ? (
          <Button variant="primary" trailingIcon="arrow-right" loading={save.isPending} onClick={() => void go(step + 1)} data-testid="onboarding-next">
            {step === 0 ? "Get started" : "Continue"}
          </Button>
        ) : (
          <Button variant="primary" icon="check" loading={save.isPending} onClick={() => void finish()} data-testid="onboarding-finish">
            Finish setup
          </Button>
        )}
      </div>
    </div>
  );
}
