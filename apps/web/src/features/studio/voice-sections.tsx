"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { newIdempotencyKey } from "@/lib/api/client";
import { useApi } from "@/lib/api/provider";
import type { AssistantProfile, VoiceOption } from "@/lib/api/types";
import { VOICE_STATUS_LABELS } from "@/lib/labels";
import { languageName } from "@/lib/language";
import { useSystemStatus, useVoiceConsent, useVoices, useVoiceStatus } from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Checkbox, Field, Select, Switch, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { useToast } from "@/components/ui/toast";
import { SettingsCard } from "./settings-card";

const VOICE_LOCALES = ["en-IN", "hi-IN", "kn-IN"];

const STATUS_TONE: Record<string, Tone> = {
  not_enrolled: "neutral",
  consent_recorded: "info",
  pending_provider_approval: "warning",
  ready: "success",
  failed: "danger",
  deleted: "neutral",
};

function voiceLabel(voice: VoiceOption): string {
  return `${voice.display_name} · ${voice.gender}${voice.note?.toLowerCase().startsWith("default") ? " · default" : ""}`;
}

/** Predefined voice per language. Production voices produce audio only when a real speech provider is connected. */
export function VoiceChoices({ profile, onChange }: { profile: AssistantProfile; onChange: (next: AssistantProfile) => void }) {
  const voices = useVoices();
  const { data: status } = useSystemStatus();
  const simulatedTts = status?.tts_provider === "simulator";

  return (
    <SettingsCard
      id="voice"
      title="Assistant voice"
      description="Pick one of the predefined natural voices for each language. Sparta always introduces itself as an AI assistant, whichever voice you choose."
    >
      {voices.isPending ? <LoadingBlock label="Loading voices" lines={3} /> : null}
      {voices.isError ? <ErrorState error={voices.error} onRetry={() => void voices.refetch()} title="Couldn't load voices" /> : null}
      {voices.data ? (
        <div className="grid gap-4 sm:grid-cols-3">
          {VOICE_LOCALES.map((locale) => {
            const options = voices.data.filter((voice) => voice.locale === locale);
            if (options.length === 0) return null;
            return (
              <Field key={locale} label={`${languageName(locale)} voice`}>
                {(props) => (
                  <Select
                    {...props}
                    value={profile.voice_ids[locale] ?? ""}
                    onChange={(event) => {
                      const next = { ...profile.voice_ids };
                      if (event.target.value) next[locale] = event.target.value;
                      else delete next[locale];
                      onChange({ ...profile, voice_ids: next });
                    }}
                  >
                    <option value="">Default voice</option>
                    {options.map((voice) => (
                      <option key={voice.id} value={voice.id}>
                        {voiceLabel(voice)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            );
          })}
        </div>
      ) : null}
      {simulatedTts ? (
        <p className="flex items-start gap-2 rounded-2xl bg-info-bg px-4 py-3 text-sm text-fg" data-testid="tts-simulated-note">
          <Icon name="flask" size={18} className="mt-0.5 shrink-0 text-info" />
          <span>
            Text-to-speech is <strong className="font-semibold">simulated</strong> on this server, so no audio is produced and you cannot hear these voices here. Your choice is saved and used when a real speech provider (Azure Speech) is connected.
          </span>
        </p>
      ) : null}
    </SettingsCard>
  );
}

/** Authorised personal voice: consent, enrolment status, deletion. Provider approval cannot be completed in this app. */
export function PersonalVoice({ profile, onChange }: { profile: AssistantProfile; onChange: (next: AssistantProfile) => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: system } = useSystemStatus();
  const status = useVoiceStatus();
  const consent = useVoiceConsent(true);
  const [agree, setAgree] = useState(false);
  const [speaker, setSpeaker] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const key = useRef(newIdempotencyKey());

  const enroll = useMutation({
    mutationFn: () =>
      api.voice.enroll({ consent: true, consent_version: consent.data!.version, speaker_name: speaker.trim() }, { idempotencyKey: key.current }),
    onSuccess: (view) => {
      key.current = newIdempotencyKey();
      queryClient.setQueryData(qk.voiceStatus, view);
      setAgree(false);
      toast.success("Your consent is recorded. The voice provider still has to approve the use case before any voice is created.", { title: "Enrolment submitted" });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.voice.remove(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.voiceStatus });
      void queryClient.invalidateQueries({ queryKey: qk.assistant });
      toast.success("Your personal voice record was deleted. Sparta uses a predefined voice.", { title: "Voice deleted" });
    },
  });

  const view = status.data;
  const canUse = Boolean(view?.status === "ready" && system?.features.personal_voice);
  const enrolled = view && view.status !== "not_enrolled" && view.status !== "deleted";
  const speakerOk = speaker.trim().length >= 1 && speaker.trim().length <= 60;

  return (
    <SettingsCard
      id="personal-voice"
      title="Personal voice"
      description="Optional. A synthetic copy of your own voice may speak for you only after you give explicit consent. Sparta never creates or uses a voice without it, and the caller is always told they are speaking with an AI."
      badge={view ? <Badge tone={STATUS_TONE[view.status] ?? "neutral"}>{VOICE_STATUS_LABELS[view.status]}</Badge> : undefined}
    >
      {status.isPending ? <LoadingBlock label="Loading voice status" lines={2} /> : null}
      {status.isError ? <ErrorState error={status.error} onRetry={() => void status.refetch()} title="Couldn't load the voice status" /> : null}
      {view ? (
        <>
          <p className="text-base text-fg" data-testid="voice-detail">
            {view.detail}
          </p>
          {view.status === "pending_provider_approval" ? (
            <p className="flex items-start gap-2 rounded-2xl bg-warning-bg px-4 py-3 text-sm text-fg" data-testid="voice-pending-note">
              <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-warning" />
              <span>
                <strong className="font-semibold">Waiting for the voice provider.</strong> Provider approval cannot be completed inside this app, so Sparta keeps using a predefined voice. Nothing is spoken in your voice until the provider approves and the voice is ready.
              </span>
            </p>
          ) : null}

          {!enrolled ? (
            <div className="space-y-4 rounded-2xl border border-line bg-raised p-4">
              <h3 className="text-base font-semibold text-fg">Consent</h3>
              {consent.isPending ? <LoadingBlock label="Loading consent text" lines={3} /> : null}
              {consent.data ? (
                <>
                  <p className="sp-scroll max-h-44 overflow-y-auto rounded-xl bg-sunken p-3 text-sm leading-relaxed text-fg" tabIndex={0} aria-label="Consent text">
                    {consent.data.text}
                  </p>
                  <p className="text-xs text-muted">
                    Consent version {consent.data.version}. Supported languages: {consent.data.supported_locales.map(languageName).join(", ")}.
                  </p>
                  <Checkbox checked={agree} onChange={setAgree} label="I have read this and I consent" description="You can withdraw consent and delete the voice at any time." />
                  <Field label="Name of the person whose voice it is" required>
                    {(props) => <TextInput {...props} value={speaker} maxLength={60} onChange={(event) => setSpeaker(event.target.value)} autoComplete="off" />}
                  </Field>
                  <Button variant="primary" disabled={!agree || !speakerOk} loading={enroll.isPending} onClick={() => enroll.mutate()}>
                    Submit consent and request enrolment
                  </Button>
                </>
              ) : null}
            </div>
          ) : (
            <Button variant="danger" icon="trash" onClick={() => setConfirmDelete(true)}>
              Delete personal voice
            </Button>
          )}

          <Switch
            checked={profile.use_personal_voice}
            onChange={(checked) => onChange({ ...profile, use_personal_voice: checked })}
            disabled={!canUse}
            label="Use my personal voice on calls"
            description={
              canUse
                ? "Callers still hear that this is an AI assistant."
                : "Unavailable until the voice is ready (provider-approved) and personal voice is switched on for this server."
            }
          />
        </>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete your personal voice?"
        description="Your consent record and any voice created for you are deleted, and Sparta goes back to a predefined voice. You can enrol again later."
        confirmLabel="Delete voice"
        tone="danger"
        onConfirm={() => remove.mutateAsync()}
      />
    </SettingsCard>
  );
}
