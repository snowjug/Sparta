"use client";

import { useMutation } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { ScreeningStrictness } from "@/lib/api/enums";
import { SCREENING_STRICTNESS } from "@/lib/api/enums";
import { useApi } from "@/lib/api/provider";
import type { AssistantProfile, UserPreferences } from "@/lib/api/types";
import { STRICTNESS_LABELS, humanize } from "@/lib/labels";
import { htmlLang, languageName } from "@/lib/language";
import { useScenarios, useSystemStatus, useVoices } from "@/lib/query/hooks";
import { Badge } from "@/components/ui/badge";
import { Button, LinkButton } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Checkbox, Field, RangeField, SegmentedControl, Select, Switch, TextInput } from "@/components/ui/form";
import { Icon, type IconName } from "@/components/ui/icon";
import { RiskBadge } from "@/components/call/badges";
import { Transcript } from "@/components/call/transcript";
import { SimulationBadge, connectionName, isLocalSip, providerName, pstnName, speechName, takeoverName } from "@/components/shell/provider-badge";
import { DisclosurePreviewBlock } from "./disclosure-block";

export interface StepProps {
  prefs: UserPreferences;
  profile: AssistantProfile;
  setPrefs: (next: UserPreferences) => void;
  setProfile: (next: AssistantProfile) => void;
  errors: Record<string, string>;
}

export const STEP_TITLES = [
  "Welcome to Sparta",
  "Sparta always says it is an AI",
  "Privacy and retention",
  "Languages",
  "Assistant voice",
  "How careful Sparta should be",
  "Trusted contacts",
  "See it work",
  "Phone connection",
] as const;

function Point({ icon, title, children }: { icon: IconName; title: string; children: string }) {
  return (
    <li className="flex items-start gap-4">
      <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Icon name={icon} size={22} />
      </span>
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        <p className="text-base text-muted">{children}</p>
      </div>
    </li>
  );
}

export function WelcomeStep() {
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">
        Sparta is an AI call assistant. It answers calls from people you do not know, finds out who they are and why they are calling, and tells you only what matters.
      </p>
      <ul className="space-y-5">
        <Point icon="phone" title="Answers for you">
          Unknown callers talk to your assistant first. Genuine calls are passed to you; scams are ended politely.
        </Point>
        <Point icon="language" title="Speaks your languages">
          English, Hindi and Kannada, including Hinglish and Kanglish, and it follows the caller if they switch language mid-call.
        </Point>
        <Point icon="lock" title="Protects what is yours">
          It never gives out OTPs, PINs, passwords or personal details, and it shows you the evidence behind every decision.
        </Point>
      </ul>
      <p className="rounded-2xl bg-raised px-4 py-3 text-sm text-muted">
        This takes about two minutes. You can change everything later in Assistant Studio and the Safety Center.
      </p>
    </div>
  );
}

export function DisclosureStep({ profile, setProfile, errors }: StepProps) {
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">
        Every caller is told, at the start of the call, that they are talking to an AI assistant. This is always on and cannot be switched off. Sparta never pretends to be you.
      </p>
      <Field label="Your name, as Sparta says it" error={errors.owner_display_name} hint="Callers hear: “Hi, I'm your name's AI call assistant.”" required>
        {(props) => (
          <TextInput {...props} value={profile.owner_display_name} maxLength={60} autoComplete="off" onChange={(event) => setProfile({ ...profile, owner_display_name: event.target.value })} />
        )}
      </Field>
      <DisclosurePreviewBlock draftName={profile.owner_display_name} />
    </div>
  );
}

const RETENTION_CHOICES: Array<[number, string, string]> = [
  [0, "Don't keep", "Delete the transcript right after the call"],
  [1, "1 day", "Just enough to read it"],
  [7, "7 days", "Recommended"],
  [30, "30 days", "A month of history"],
];

export function PrivacyStep({ prefs, setPrefs }: StepProps) {
  const retention = prefs.retention;
  const set = (patch: Partial<UserPreferences["retention"]>) => setPrefs({ ...prefs, retention: { ...retention, ...patch } });
  const days = RETENTION_CHOICES.some(([value]) => value === retention.transcript_retention_days) ? String(retention.transcript_retention_days) : "7";
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">Sparta keeps as little as it can. You choose how long transcripts stay, and you can delete everything at any time.</p>
      <Switch
        checked={retention.store_transcripts}
        onChange={(checked) => set({ store_transcripts: checked })}
        label="Keep call transcripts"
        description="If off, Sparta still saves a one-sentence summary, the risk level and the category."
      />
      {retention.store_transcripts ? (
        <SegmentedControl
          legend="Delete transcripts after"
          value={days}
          onChange={(value) => set({ transcript_retention_days: Number(value) })}
          options={RETENTION_CHOICES.map(([value, label, description]) => ({ value: String(value), label, description }))}
        />
      ) : null}
      <ul className="space-y-2 rounded-2xl bg-raised px-4 py-3 text-sm text-fg">
        <li className="flex items-start gap-2">
          <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent" />
          Raw call audio is never stored.
        </li>
        <li className="flex items-start gap-2">
          <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent" />
          Phone numbers are shown masked, like +91 98•• ••21.
        </li>
        <li className="flex items-start gap-2">
          <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent" />
          Call audio is never used to train models.
        </li>
      </ul>
      <Switch
        checked={retention.store_full_caller_number}
        onChange={(checked) => set({ store_full_caller_number: checked })}
        label="Keep the full caller number (encrypted)"
        description="Off by default. Only matters if you want to match future calls to the exact number."
      />
    </div>
  );
}

export function LanguageStep({ prefs, setPrefs, errors }: StepProps) {
  const { data: status } = useSystemStatus();
  const supported = (status?.languages ?? [
    { code: "en-IN", name: "English", native_name: "English", status: "supported" as const },
    { code: "hi-IN", name: "Hindi", native_name: "हिन्दी", status: "supported" as const },
    { code: "kn-IN", name: "Kannada", native_name: "ಕನ್ನಡ", status: "supported" as const },
  ]).filter((language) => language.status === "supported");
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">Choose the languages Sparta can use. If a caller switches language, Sparta follows.</p>
      <Field label="Your primary language" error={errors.primary_language}>
        {(props) => (
          <Select
            {...props}
            value={prefs.primary_language}
            onChange={(event) => {
              const primary = event.target.value;
              setPrefs({ ...prefs, primary_language: primary, enabled_languages: prefs.enabled_languages.includes(primary) ? prefs.enabled_languages : [...prefs.enabled_languages, primary] });
            }}
          >
            {supported.map((language) => (
              <option key={language.code} value={language.code}>
                {language.name} · {language.native_name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <fieldset>
        <legend className="mb-1 text-sm font-medium text-fg">Sparta may speak</legend>
        {supported.map((language) => (
          <Checkbox
            key={language.code}
            checked={prefs.enabled_languages.includes(language.code)}
            disabled={language.code === prefs.primary_language}
            onChange={(checked) =>
              setPrefs({
                ...prefs,
                enabled_languages: checked ? [...prefs.enabled_languages, language.code] : prefs.enabled_languages.filter((code) => code !== language.code),
              })
            }
            label={`${language.name} · ${language.native_name}`}
            description={language.code === prefs.primary_language ? "Your primary language is always on." : undefined}
          />
        ))}
      </fieldset>
      <Switch
        checked={prefs.auto_detect_language}
        onChange={(checked) => setPrefs({ ...prefs, auto_detect_language: checked })}
        label="Detect the caller's language automatically"
        description="Recommended. Hinglish (Hindi and English) and Kanglish (Kannada and English) are understood too."
      />
    </div>
  );
}

export function VoiceStep({ profile, setProfile }: StepProps) {
  const voices = useVoices();
  const { data: status } = useSystemStatus();
  const locales = ["en-IN", "hi-IN", "kn-IN"];
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">Pick a natural voice for each language. These are predefined voices; a personal voice is optional and needs your explicit consent later, in Assistant Studio.</p>
      {voices.isPending ? <LoadingBlock label="Loading voices" lines={3} /> : null}
      {voices.isError ? <ErrorState error={voices.error} onRetry={() => void voices.refetch()} title="Couldn't load voices" /> : null}
      {voices.data ? (
        <div className="grid gap-4 sm:grid-cols-3">
          {locales.map((locale) => (
            <Field key={locale} label={`${languageName(locale)} voice`}>
              {(props) => (
                <Select
                  {...props}
                  value={profile.voice_ids[locale] ?? ""}
                  onChange={(event) => {
                    const next = { ...profile.voice_ids };
                    if (event.target.value) next[locale] = event.target.value;
                    else delete next[locale];
                    setProfile({ ...profile, voice_ids: next });
                  }}
                >
                  <option value="">Default voice</option>
                  {voices.data.filter((voice) => voice.locale === locale).map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.display_name} · {voice.gender}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          ))}
        </div>
      ) : null}
      <SegmentedControl
        legend="Response style"
        value={profile.response_style}
        onChange={(response_style) => setProfile({ ...profile, response_style })}
        options={[
          { value: "concise", label: "Concise", description: "Short, to the point." },
          { value: "warm", label: "Warm", description: "Friendly and reassuring." },
          { value: "formal", label: "Formal", description: "Polite and professional." },
        ]}
      />
      <RangeField
        label="Speaking speed"
        value={profile.speaking_rate}
        min={0.7}
        max={1.3}
        step={0.05}
        onChange={(speaking_rate) => setProfile({ ...profile, speaking_rate: Math.round(speaking_rate * 100) / 100 })}
        format={(value) => `${value.toFixed(2)}×`}
      />
      {status?.tts_provider === "simulator" ? (
        <p className="flex items-start gap-2 rounded-2xl bg-info-bg px-4 py-3 text-sm text-fg">
          <Icon name="flask" size={18} className="mt-0.5 shrink-0 text-info" />
          Speech is simulated on this server, so you will not hear these voices yet. Your choices are saved for when a real speech provider is connected.
        </p>
      ) : null}
    </div>
  );
}

export function StrictnessStep({ prefs, setPrefs }: StepProps) {
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">How careful should Sparta be? You can change this whenever you like.</p>
      <SegmentedControl<ScreeningStrictness>
        legend="Screening strictness"
        value={prefs.strictness}
        onChange={(strictness) => setPrefs({ ...prefs, strictness })}
        options={SCREENING_STRICTNESS.map((value) => ({ value, label: STRICTNESS_LABELS[value].label, description: STRICTNESS_LABELS[value].description }))}
        stacked
      />
      <SegmentedControl<UserPreferences["unknown_caller_behavior"]>
        legend="Unknown callers"
        value={prefs.unknown_caller_behavior}
        onChange={(unknown_caller_behavior) => setPrefs({ ...prefs, unknown_caller_behavior })}
        options={[
          { value: "screen", label: "Screen them", description: "Sparta answers and finds out who is calling." },
          { value: "silence", label: "Silence them", description: "Ring silently; the call shows in your history." },
          { value: "allow", label: "Let them through", description: "Ring through like a normal call." },
        ]}
        stacked
      />
    </div>
  );
}

export function TrustedStep({ prefs, setPrefs }: StepProps) {
  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">You can mark any caller as trusted from a call or from the Safety Center. What should happen when a trusted contact calls?</p>
      <SegmentedControl<UserPreferences["trusted_contact_behavior"]>
        legend="Trusted contacts"
        value={prefs.trusted_contact_behavior}
        onChange={(trusted_contact_behavior) => setPrefs({ ...prefs, trusted_contact_behavior })}
        options={[
          { value: "allow_directly", label: "Ring straight through", description: "Recommended. Family and colleagues never wait for the assistant." },
          { value: "screen_anyway", label: "Screen them too", description: "Even trusted numbers talk to the assistant first." },
        ]}
        stacked
      />
    </div>
  );
}

const WALKTHROUGH = ["bank-otp-en", "kyc-hinglish", "delivery-legit"];

export function WalkthroughStep() {
  const api = useApi();
  const scenarios = useScenarios();
  const [scenarioId, setScenarioId] = useState(WALKTHROUGH[0]!);
  const replay = useMutation({ mutationFn: () => api.simulator.replay({ scenario_id: scenarioId }) });
  const choices = (scenarios.data ?? []).filter((scenario) => WALKTHROUGH.includes(scenario.id));
  const call = replay.data?.call;

  return (
    <div className="space-y-6">
      <p className="text-pretty text-lg text-fg">
        Watch Sparta handle a recorded call. It runs through the real safety pipeline, but no phone call is involved: everything here is <strong className="font-semibold">simulated</strong>.
      </p>
      {scenarios.isPending ? <LoadingBlock label="Loading scenarios" lines={2} /> : null}
      {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} title="Couldn't load the scenarios" /> : null}
      {choices.length > 0 ? (
        <SegmentedControl
          legend="Pick a call"
          value={scenarioId}
          onChange={(value) => {
            setScenarioId(value);
            replay.reset();
          }}
          options={choices.map((scenario) => ({ value: scenario.id, label: scenario.title, description: scenario.description }))}
          stacked
        />
      ) : null}
      <Button variant="primary" icon="play" loading={replay.isPending} onClick={() => replay.mutate()} data-testid="run-walkthrough">
        Run this call
      </Button>

      {call ? (
        <div className="space-y-4 rounded-3xl border border-line bg-raised p-4" data-testid="walkthrough-result" aria-live="polite">
          <div className="flex flex-wrap items-center gap-2">
            <SimulationBadge simulated />
            <RiskBadge level={call.risk_level} />
            {call.action_taken ? <Badge tone="accent">{humanize(call.action_taken)}</Badge> : null}
          </div>
          <Transcript turns={call.turns} signals={call.risk?.signals ?? []} showTranslation={false} label="Sample call transcript" />
          {call.summary ? (
            <p className="rounded-2xl bg-surface px-4 py-3 text-base text-fg">
              <span className="font-semibold">Summary: </span>
              <span lang={htmlLang("en-IN")}>{call.summary.text}</span>
            </p>
          ) : null}
          <p className="text-xs text-muted">
            Deterministic replay · checksum <span className="font-mono">{replay.data?.checksum.slice(0, 16)}…</span>
          </p>
        </div>
      ) : null}
      <LinkButton href="/simulator" variant="secondary" icon="flask" trailingIcon="arrow-right">
        Open the Simulator Lab (you can type your own caller)
      </LinkButton>
    </div>
  );
}

function TelephonyRow({ label, testId, children }: { label: string; testId?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex items-center gap-2 text-base font-semibold text-fg" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

export function TelephonyStep() {
  const { data: status, isPending, error, refetch } = useSystemStatus();
  if (isPending) return <LoadingBlock label="Checking the phone connection" lines={3} />;
  if (error || !status) return <ErrorState error={error} onRetry={() => void refetch()} title="Couldn't check the phone connection" />;
  const t = status.telephony;
  const localSip = isLocalSip(t.provider, t.connection);
  return (
    <div className="space-y-6" data-testid="telephony-step">
      <p className="text-pretty text-lg text-fg">This is how calls reach Sparta on this server. We show it plainly so there are no surprises.</p>
      <dl className="divide-y divide-line rounded-3xl border border-line bg-raised px-5">
        <TelephonyRow label="Telephony provider">
          {providerName(t.provider)}
          <SimulationBadge simulated={t.simulated} provider={t.provider} connection={t.connection} />
        </TelephonyRow>
        <TelephonyRow label="Connection" testId="telephony-connection">
          {connectionName(t.connection)}
        </TelephonyRow>
        <TelephonyRow label={localSip ? "Local SIP calls" : "Real phone calls"}>{t.live_calls_supported ? "Supported" : "Not connected"}</TelephonyRow>
        {t.pstn === "not_configured" ? (
          <TelephonyRow label="Phone network (PSTN)" testId="telephony-pstn">
            {pstnName(t.pstn)}
          </TelephonyRow>
        ) : null}
        <TelephonyRow label="Speech" testId="telephony-speech">
          {speechName(status.stt_provider, status.tts_provider)}
        </TelephonyRow>
        <TelephonyRow label="Take over" testId="telephony-takeover">
          {takeoverName(t.takeover)}
        </TelephonyRow>
        <TelephonyRow label="Forwarding number" testId="forwarding-number">
          {t.forwarding_number ?? (localSip ? "Not used with local SIP" : "Not set")}
        </TelephonyRow>
      </dl>
      <p className="text-base text-muted">{t.note}</p>
      {localSip ? (
        <p className="flex items-start gap-3 rounded-2xl bg-info-bg px-4 py-3 text-sm text-fg" data-testid="local-sip-explained">
          <Icon name="info" size={18} className="mt-0.5 shrink-0 text-info" />
          <span>
            <strong className="font-semibold">Local SIP</strong> means SIP phones on your network can call Sparta. Normal phone numbers cannot reach it this way: that needs a carrier, a phone number and a SIP trunk.
          </span>
        </p>
      ) : t.forwarding_number === null ? (
        <p className="flex items-start gap-3 rounded-2xl bg-info-bg px-4 py-3 text-sm text-fg" data-testid="forwarding-explained">
          <Icon name="info" size={18} className="mt-0.5 shrink-0 text-info" />
          <span>
            A <strong className="font-semibold">forwarding number</strong> is the number your phone forwards unknown or unanswered calls to, so that Sparta can answer them. None is configured on this server, so real incoming calls cannot reach Sparta yet. You can still try everything in the Simulator Lab. Connecting a real telephony provider is an operator task.
          </span>
        </p>
      ) : null}
      <p className="text-sm text-muted">Android phones can additionally screen calls on the device itself (allow, silence or reject), but that cannot answer a call or hear its audio.</p>
    </div>
  );
}
