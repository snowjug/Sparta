"use client";

import type { ReactNode } from "react";
import { RESPONSE_STYLES, SCREENING_STRICTNESS, type CallCategory } from "@/lib/api/enums";
import type { AssistantProfile, UserPreferences } from "@/lib/api/types";
import { categoryLabel, STRICTNESS_LABELS } from "@/lib/labels";
import { useSystemStatus } from "@/lib/query/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, RangeField, SegmentedControl, Select, Switch, TextInput } from "@/components/ui/form";
import { SettingsCard } from "./settings-card";

export type FieldErrors = Record<string, string>;

interface PrefsProps {
  prefs: UserPreferences;
  onChange: (next: UserPreferences) => void;
  errors?: FieldErrors;
}

interface ProfileProps {
  profile: AssistantProfile;
  onChange: (next: AssistantProfile) => void;
  errors?: FieldErrors;
}

const STYLE_COPY: Record<(typeof RESPONSE_STYLES)[number], { label: string; description: string }> = {
  concise: { label: "Concise", description: "Short, to the point." },
  warm: { label: "Warm", description: "Friendly and reassuring." },
  formal: { label: "Formal", description: "Polite and professional." },
};

const UNKNOWN_COPY: Record<UserPreferences["unknown_caller_behavior"], string> = {
  screen: "Sparta answers and finds out who is calling",
  silence: "Ring silently, and show the call in your history",
  allow: "Let unknown callers ring through as normal",
};

const TRUSTED_COPY: Record<UserPreferences["trusted_contact_behavior"], string> = {
  allow_directly: "Trusted callers ring straight through to you",
  screen_anyway: "Screen trusted callers too",
};

const ESCALATION_CHOICES: CallCategory[] = [
  "legitimate_delivery",
  "legitimate_urgent",
  "legitimate_recruiter",
  "legitimate_support_callback",
  "legitimate_personal",
  "legitimate_appointment",
];

function Grid({ children, cols = 2 }: { children: ReactNode; cols?: 1 | 2 | 3 }) {
  return <div className={cols === 1 ? "grid gap-4" : cols === 2 ? "grid gap-4 sm:grid-cols-2" : "grid gap-4 sm:grid-cols-3"}>{children}</div>;
}

export function LanguageSection({ prefs, onChange, errors = {} }: PrefsProps) {
  const { data: status } = useSystemStatus();
  const languages = status?.languages ?? [
    { code: "en-IN", name: "English", native_name: "English", status: "supported" as const },
    { code: "hi-IN", name: "Hindi", native_name: "हिन्दी", status: "supported" as const },
    { code: "kn-IN", name: "Kannada", native_name: "ಕನ್ನಡ", status: "supported" as const },
  ];
  const supported = languages.filter((language) => language.status === "supported");
  // Caller speech is only translated when the backend reports a translation provider (never in the built-in simulator build).
  const translationAvailable = status?.features.translation === true;

  function toggle(code: string, checked: boolean) {
    const set = new Set(prefs.enabled_languages);
    if (checked) set.add(code);
    else set.delete(code);
    onChange({ ...prefs, enabled_languages: [...set] });
  }

  return (
    <SettingsCard
      id="languages"
      title="Languages"
      description="Sparta understands English, Hindi (including Hinglish) and Kannada (including Kanglish), and keeps listening in case the caller switches language mid-call."
    >
      <Grid>
        <Field label="Your primary language" error={errors.primary_language}>
          {(props) => (
            <Select
              {...props}
              value={prefs.primary_language}
              onChange={(event) => {
                const primary = event.target.value;
                onChange({ ...prefs, primary_language: primary, enabled_languages: prefs.enabled_languages.includes(primary) ? prefs.enabled_languages : [...prefs.enabled_languages, primary] });
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
        <Field
          label="Translate transcripts to"
          hint={
            translationAvailable
              ? "Shown under each turn when you switch on translation."
              : "Translating caller speech needs a language-model provider and is not available in this build. Assistant lines always include an English rendering."
          }
          error={errors.translate_transcripts_to}
        >
          {(props) => (
            <Select
              {...props}
              // Not a dead control: without a translation provider the select is disabled and says why. The saved value is left untouched.
              disabled={!translationAvailable}
              value={prefs.translate_transcripts_to ?? ""}
              onChange={(event) => onChange({ ...prefs, translate_transcripts_to: event.target.value || null })}
            >
              <option value="">Don&apos;t translate</option>
              {supported.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </Grid>
      <fieldset>
        <legend className="mb-1 text-sm font-medium text-fg">Languages Sparta may use with callers</legend>
        <div className="grid gap-x-6 sm:grid-cols-2">
          {languages.map((language) => (
            <div key={language.code} className="flex items-center justify-between gap-3">
              <Checkbox
                checked={prefs.enabled_languages.includes(language.code)}
                onChange={(checked) => toggle(language.code, checked)}
                disabled={language.status !== "supported" || language.code === prefs.primary_language}
                label={`${language.name} · ${language.native_name}`}
                description={language.code === prefs.primary_language ? "Your primary language is always on." : undefined}
              />
              {language.status === "planned" ? <Badge tone="neutral">Planned</Badge> : null}
            </div>
          ))}
        </div>
        {errors.enabled_languages ? <p className="mt-1 text-sm font-medium text-danger">{errors.enabled_languages}</p> : null}
      </fieldset>
      <Switch
        checked={prefs.auto_detect_language}
        onChange={(checked) => onChange({ ...prefs, auto_detect_language: checked })}
        label="Detect the caller's language automatically"
        description="Recommended. Callers often switch between languages, for example English to Hindi to Kannada."
      />
    </SettingsCard>
  );
}

export function StyleSection({ profile, onChange, errors = {} }: ProfileProps) {
  return (
    <SettingsCard id="style" title="How Sparta speaks" description="Sparta introduces itself as your AI call assistant. It never pretends to be you.">
      <Field
        label="Your name, as Sparta says it"
        hint={`Callers hear: “Hi, I'm ${profile.owner_display_name.trim() || "…"}'s AI call assistant.”`}
        error={errors.owner_display_name}
        required
      >
        {(props) => <TextInput {...props} value={profile.owner_display_name} maxLength={60} onChange={(event) => onChange({ ...profile, owner_display_name: event.target.value })} autoComplete="off" />}
      </Field>
      <SegmentedControl
        legend="Response style"
        value={profile.response_style}
        onChange={(response_style) => onChange({ ...profile, response_style })}
        options={RESPONSE_STYLES.map((value) => ({ value, label: STYLE_COPY[value].label, description: STYLE_COPY[value].description }))}
      />
      <RangeField
        label="Speaking speed"
        value={profile.speaking_rate}
        min={0.7}
        max={1.3}
        step={0.05}
        onChange={(speaking_rate) => onChange({ ...profile, speaking_rate: Math.round(speaking_rate * 100) / 100 })}
        format={(value) => `${value.toFixed(2)}×`}
        hint="1.00× is normal speed."
      />
    </SettingsCard>
  );
}

export function ScreeningSection({ prefs, onChange, errors = {} }: PrefsProps) {
  return (
    <SettingsCard id="screening" title="Screening" description="How careful Sparta is, and what it does with callers it does not know.">
      <SegmentedControl
        legend="Screening strictness"
        value={prefs.strictness}
        onChange={(strictness) => onChange({ ...prefs, strictness })}
        options={SCREENING_STRICTNESS.map((value) => ({ value, label: STRICTNESS_LABELS[value].label, description: STRICTNESS_LABELS[value].description }))}
        stacked
      />
      <Grid>
        <Field label="Unknown callers" error={errors.unknown_caller_behavior}>
          {(props) => (
            <Select {...props} value={prefs.unknown_caller_behavior} onChange={(event) => onChange({ ...prefs, unknown_caller_behavior: event.target.value as UserPreferences["unknown_caller_behavior"] })}>
              {(Object.keys(UNKNOWN_COPY) as Array<keyof typeof UNKNOWN_COPY>).map((value) => (
                <option key={value} value={value}>
                  {UNKNOWN_COPY[value]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Trusted contacts" error={errors.trusted_contact_behavior}>
          {(props) => (
            <Select {...props} value={prefs.trusted_contact_behavior} onChange={(event) => onChange({ ...prefs, trusted_contact_behavior: event.target.value as UserPreferences["trusted_contact_behavior"] })}>
              {(Object.keys(TRUSTED_COPY) as Array<keyof typeof TRUSTED_COPY>).map((value) => (
                <option key={value} value={value}>
                  {TRUSTED_COPY[value]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </Grid>
      <Grid cols={3}>
        <RangeField
          label="First silence timeout"
          value={prefs.silence_first_timeout_s}
          min={3}
          max={30}
          step={1}
          onChange={(silence_first_timeout_s) => onChange({ ...prefs, silence_first_timeout_s })}
          format={(value) => `${value} s`}
          hint="Before Sparta asks again."
        />
        <RangeField
          label="Second silence timeout"
          value={prefs.silence_second_timeout_s}
          min={3}
          max={30}
          step={1}
          onChange={(silence_second_timeout_s) => onChange({ ...prefs, silence_second_timeout_s })}
          format={(value) => `${value} s`}
          hint="Before Sparta ends the call."
        />
        <RangeField
          label="Longest call"
          value={prefs.max_call_duration_s}
          min={30}
          max={900}
          step={30}
          onChange={(max_call_duration_s) => onChange({ ...prefs, max_call_duration_s })}
          format={(value) => `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")} min`}
          hint="Sparta ends calls that run longer."
        />
      </Grid>
      <Field
        label="Number to bridge when you take over"
        hint="Used only by a real telephony provider when you tap Take Over. The simulator never calls it. Leave empty if unsure."
        error={errors.takeover_number}
      >
        {(props) => (
          <TextInput
            {...props}
            type="tel"
            inputMode="tel"
            autoComplete="off"
            value={prefs.takeover_number ?? ""}
            placeholder="+91 …"
            maxLength={20}
            onChange={(event) => onChange({ ...prefs, takeover_number: event.target.value.trim() ? event.target.value : null })}
          />
        )}
      </Field>
    </SettingsCard>
  );
}

export function EscalationSection({ prefs, onChange, errors = {} }: PrefsProps) {
  const rules = prefs.escalation;
  const set = (patch: Partial<UserPreferences["escalation"]>) => onChange({ ...prefs, escalation: { ...rules, ...patch } });
  return (
    <SettingsCard id="escalation" title="When Sparta should ask you" description="Genuine-looking calls are escalated to you instead of being ended. Choose which kinds, and how long Sparta waits for your answer.">
      <fieldset>
        <legend className="mb-1 text-sm font-medium text-fg">Escalate these calls to me</legend>
        <div className="grid gap-x-6 sm:grid-cols-2">
          {ESCALATION_CHOICES.map((category) => (
            <Checkbox
              key={category}
              checked={rules.escalate_categories.includes(category)}
              onChange={(checked) =>
                set({ escalate_categories: checked ? [...rules.escalate_categories, category] : rules.escalate_categories.filter((c) => c !== category) })
              }
              label={categoryLabel(category)}
            />
          ))}
        </div>
        {errors.escalate_categories ? <p className="mt-1 text-sm font-medium text-danger">{errors.escalate_categories}</p> : null}
      </fieldset>
      {/* The engine escalates by category only and ignores this value: a disabled switch (stored value untouched), not a dead control. */}
      <Switch
        checked={rules.escalate_uncertain_urgent}
        onChange={() => undefined}
        disabled
        label="Ask me when a call sounds urgent but Sparta is unsure"
        description="Saved, but Sparta does not act on this yet; escalation follows the categories above."
      />
      <Switch checked={rules.auto_end_high_risk} onChange={(checked) => set({ auto_end_high_risk: checked })} label="End high-risk calls automatically" description="Recommended. Sparta refuses, explains it cannot help, and hangs up." />
      <RangeField
        label="How long Sparta waits for your answer"
        value={rules.owner_response_timeout_s}
        min={5}
        max={180}
        step={5}
        onChange={(owner_response_timeout_s) => set({ owner_response_timeout_s })}
        format={(value) => `${value} s`}
        hint="After this, Sparta takes a message instead."
      />
    </SettingsCard>
  );
}

export function NotificationSection({ prefs, onChange, errors = {} }: PrefsProps) {
  const notifications = prefs.notifications;
  const set = (patch: Partial<UserPreferences["notifications"]>) => onChange({ ...prefs, notifications: { ...notifications, ...patch } });
  return (
    <SettingsCard id="notifications" title="Notifications" description="Push notifications need a configured push provider. These preferences are saved now and used when it is connected.">
      <Switch checked={notifications.notify_on_escalation} onChange={(checked) => set({ notify_on_escalation: checked })} label="Notify me when a call needs me" />
      <Switch checked={notifications.notify_on_high_risk} onChange={(checked) => set({ notify_on_high_risk: checked })} label="Notify me about high-risk calls" description="Off by default so Sparta is not constantly alarming." />
      <Switch checked={notifications.include_transcript_lines} onChange={(checked) => set({ include_transcript_lines: checked })} label="Show the latest important lines in notifications" />
      <Grid>
        <Field label="Quiet hours start" error={errors.quiet_hours_start}>
          {(props) => <TextInput {...props} type="time" value={notifications.quiet_hours_start ?? ""} onChange={(event) => set({ quiet_hours_start: event.target.value || null })} />}
        </Field>
        <Field label="Quiet hours end" error={errors.quiet_hours_end}>
          {(props) => <TextInput {...props} type="time" value={notifications.quiet_hours_end ?? ""} onChange={(event) => set({ quiet_hours_end: event.target.value || null })} />}
        </Field>
      </Grid>
      {notifications.quiet_hours_start || notifications.quiet_hours_end ? (
        <Button variant="secondary" size="sm" onClick={() => set({ quiet_hours_start: null, quiet_hours_end: null })}>
          Clear quiet hours
        </Button>
      ) : null}
    </SettingsCard>
  );
}
