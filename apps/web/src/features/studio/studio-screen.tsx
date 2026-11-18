"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { fieldErrors } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { AssistantProfile, UserPreferences } from "@/lib/api/types";
import { useAssistantProfile, usePreferences } from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";
import { PageHeader } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import {
  EscalationSection,
  LanguageSection,
  NotificationSection,
  ScreeningSection,
  StyleSection,
  type FieldErrors,
} from "./behaviour-sections";
import { DisclosurePreview, SafeReplyPreview } from "./preview-sections";
import { PersonalVoice, VoiceChoices } from "./voice-sections";

const SECTIONS: Array<[string, string]> = [
  ["voice", "Voice"],
  ["personal-voice", "Personal voice"],
  ["disclosure", "AI disclosure"],
  ["languages", "Languages"],
  ["style", "Style"],
  ["screening", "Screening"],
  ["escalation", "Escalation"],
  ["safe-reply", "Safe-reply preview"],
  ["notifications", "Notifications"],
];

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function StudioScreen() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const prefsQuery = usePreferences();
  const profileQuery = useAssistantProfile();
  const [prefsDraft, setPrefsDraft] = useState<UserPreferences | null>(null);
  const [profileDraft, setProfileDraft] = useState<AssistantProfile | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});

  const prefs = prefsDraft ?? prefsQuery.data;
  const profile = profileDraft ?? profileQuery.data;
  const prefsDirty = Boolean(prefsDraft && prefsQuery.data && !same(prefsDraft, prefsQuery.data));
  const profileDirty = Boolean(profileDraft && profileQuery.data && !same(profileDraft, profileQuery.data));
  const dirty = prefsDirty || profileDirty;

  const save = useMutation({
    mutationFn: async () => {
      const saved: { prefs?: UserPreferences; profile?: AssistantProfile } = {};
      if (prefsDirty && prefsDraft) saved.prefs = await api.preferences.put(prefsDraft);
      if (profileDirty && profileDraft) saved.profile = await api.assistant.put(profileDraft);
      return saved;
    },
    onSuccess: (saved) => {
      if (saved.prefs) queryClient.setQueryData(qk.preferences, saved.prefs);
      if (saved.profile) queryClient.setQueryData(qk.assistant, saved.profile);
      setPrefsDraft(null);
      setProfileDraft(null);
      setErrors({});
      void queryClient.invalidateQueries({ queryKey: ["assistant", "preview"] });
      void queryClient.invalidateQueries({ queryKey: qk.home });
      toast.success("Your changes are saved and apply to the next call.", { title: "Settings saved" });
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });

  function discard() {
    setPrefsDraft(null);
    setProfileDraft(null);
    setErrors({});
  }

  if (prefsQuery.isPending || profileQuery.isPending) return <LoadingBlock label="Loading your assistant settings" lines={6} />;
  if (prefsQuery.isError) return <ErrorState error={prefsQuery.error} onRetry={() => void prefsQuery.refetch()} title="Couldn't load your preferences" />;
  if (profileQuery.isError) return <ErrorState error={profileQuery.error} onRetry={() => void profileQuery.refetch()} title="Couldn't load your assistant profile" />;
  if (!prefs || !profile) return null;

  const setPrefs = (next: UserPreferences) => setPrefsDraft(next);
  const setProfile = (next: AssistantProfile) => setProfileDraft(next);

  return (
    <div className="space-y-6 pb-24">
      <PageHeader
        title="Assistant Studio"
        description="Shape how your AI call assistant sounds and how careful it is. Sparta always tells callers it is an AI, and it never speaks in your voice without your explicit consent."
      />

      <nav aria-label="Settings sections" className="-mx-1 overflow-x-auto px-1 pb-1">
        <ul className="flex gap-2">
          {SECTIONS.map(([id, label]) => (
            <li key={id} className="shrink-0">
              <a href={`#${id}`} className="inline-flex min-h-11 items-center rounded-full border border-line bg-surface px-4 text-sm font-medium text-fg hover:bg-raised">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="space-y-6" data-testid="studio-sections">
        <VoiceChoices profile={profile} onChange={setProfile} />
        <PersonalVoice profile={profile} onChange={setProfile} />
        <DisclosurePreview profile={profile} savedName={profileQuery.data?.owner_display_name ?? ""} />
        <LanguageSection prefs={prefs} onChange={setPrefs} errors={errors} />
        <StyleSection profile={profile} onChange={setProfile} errors={errors} />
        <ScreeningSection prefs={prefs} onChange={setPrefs} errors={errors} />
        <EscalationSection prefs={prefs} onChange={setPrefs} errors={errors} />
        <SafeReplyPreview profile={profile} />
        <NotificationSection prefs={prefs} onChange={setPrefs} errors={errors} />
      </div>

      {dirty ? (
        <div
          role="region"
          aria-label="Unsaved changes"
          data-testid="save-bar"
          className="fixed inset-x-3 bottom-[4.75rem] z-30 mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-3xl border border-line-strong bg-surface p-3 pl-5 shadow-card lg:bottom-6 lg:left-[18rem] lg:right-6"
        >
          <p className="flex items-center gap-2 text-sm font-medium text-fg">
            <Icon name="info" size={18} className="text-accent" />
            You have unsaved changes.
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={discard} disabled={save.isPending}>
              Discard
            </Button>
            <Button variant="primary" icon="check" loading={save.isPending} onClick={() => save.mutate()} data-testid="save-settings">
              Save changes
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
