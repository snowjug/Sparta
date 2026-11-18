"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/lib/api/provider";
import type { AssistantProfile } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";
import { categoryLabel } from "@/lib/labels";
import { htmlLang, languageName } from "@/lib/language";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Field, Select, TextArea } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { BrowserVoiceButton } from "@/components/call/browser-voice-button";
import { RiskBadge } from "@/components/call/badges";
import { SignalList } from "@/components/call/risk-panel";
import { SettingsCard } from "./settings-card";

const LANGUAGE_CHOICES = ["auto", "en-IN", "hi-IN", "kn-IN"];

const EXAMPLES = [
  "I'm calling from your bank. Please read me the OTP you just received.",
  "Main HDFC se bol raha hoon, aapka KYC expire ho gaya hai.",
  "Nimma account block aagutte sir, ondu OTP heli please.",
  "I'm the delivery executive, I'm at your gate and can't find the flat.",
];

function LanguageSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Field label="Language">
      {(props) => (
        <Select {...props} value={value} onChange={(event) => onChange(event.target.value)}>
          {LANGUAGE_CHOICES.map((code) => (
            <option key={code} value={code}>
              {languageName(code)}
            </option>
          ))}
        </Select>
      )}
    </Field>
  );
}

/** The AI disclosure is always on. This shows exactly what callers hear first, in the chosen language. */
export function DisclosurePreview({ profile, savedName }: { profile: AssistantProfile; savedName: string }) {
  const api = useApi();
  const [language, setLanguage] = useState("auto");
  const query = useQuery({
    queryKey: ["assistant", "preview", "disclosure", language, savedName],
    queryFn: ({ signal }) => api.assistant.preview({ language }, { signal }),
    staleTime: 30_000,
  });
  const plan = query.data?.disclosure;

  return (
    <SettingsCard
      id="disclosure"
      title="AI disclosure"
      description="Callers are always told they are speaking with an AI assistant, and the assistant never claims to be you. This cannot be switched off."
      badge={
        <Badge tone="accent" icon="lock" strong>
          Always on
        </Badge>
      }
    >
      <div className="grid gap-4 sm:grid-cols-[14rem_1fr] sm:items-start">
        <LanguageSelect value={language} onChange={setLanguage} />
        <div className="min-w-0">
          {query.isPending ? <LoadingBlock label="Loading preview" lines={2} /> : null}
          {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't preview the disclosure" /> : null}
          {plan ? (
            <figure className="rounded-2xl border border-line bg-raised p-4" data-testid="disclosure-preview">
              <blockquote lang={htmlLang(plan.locale)} className="text-pretty text-lg text-fg">
                {plan.text}
              </blockquote>
              <figcaption className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
                <span>{languageName(plan.locale)}</span>
                <span className="tabular-nums">about {formatDuration(plan.est_duration_ms)} to say</span>
                {plan.transliteration ? <span>Latin script: {plan.transliteration}</span> : null}
              </figcaption>
              <div className="mt-3">
                <BrowserVoiceButton text={plan.text} lang={plan.locale} rate={profile.speaking_rate} />
              </div>
            </figure>
          ) : null}
        </div>
      </div>
    </SettingsCard>
  );
}

/** Runs the real pipeline on a sample sentence, without creating a call, and shows what Sparta would say. */
export function SafeReplyPreview({ profile }: { profile: AssistantProfile }) {
  const api = useApi();
  const [language, setLanguage] = useState("auto");
  const [sample, setSample] = useState("");
  const preview = useMutation({
    mutationFn: () => api.assistant.preview({ language, sample_text: sample.trim() }),
  });
  const result = preview.data;

  return (
    <SettingsCard
      id="safe-reply"
      title="Safe-reply preview"
      description="Type something a caller might say. Sparta runs its real safety pipeline on it and shows the reply, the risk and the evidence. No call is created and nothing is saved."
    >
      <div className="grid gap-4 sm:grid-cols-[14rem_1fr]">
        <LanguageSelect value={language} onChange={setLanguage} />
        <Field label="What the caller says" hint={`${sample.length}/400 characters`}>
          {(props) => <TextArea {...props} value={sample} maxLength={400} rows={3} onChange={(event) => setSample(event.target.value)} />}
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Example sentences">
        <span className="text-sm text-muted">Try:</span>
        {EXAMPLES.map((example) => (
          <Button key={example} variant="secondary" size="sm" onClick={() => setSample(example)}>
            {example.length > 34 ? `${example.slice(0, 33)}…` : example}
          </Button>
        ))}
      </div>
      <Button variant="primary" icon="play" disabled={sample.trim().length === 0} loading={preview.isPending} onClick={() => preview.mutate()} data-testid="run-preview">
        Preview Sparta&apos;s reply
      </Button>

      {result ? (
        <div className="space-y-4 rounded-2xl border border-line bg-raised p-4" data-testid="reply-preview" aria-live="polite">
          {result.reply ? (
            <figure>
              <figcaption className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Sparta would say</figcaption>
              <blockquote lang={htmlLang(result.reply.locale)} className="text-pretty text-lg text-fg" data-testid="reply-text">
                {result.reply.text}
              </blockquote>
              <p className="mt-2 text-sm text-muted">
                {languageName(result.reply.locale)}
                {result.reply.transliteration ? ` · ${result.reply.transliteration}` : ""}
              </p>
              <div className="mt-2">
                <BrowserVoiceButton text={result.reply.text} lang={result.reply.locale} rate={profile.speaking_rate} />
              </div>
            </figure>
          ) : (
            <p className="text-base text-fg">Sparta would not reply to that on its own.</p>
          )}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {result.risk ? <RiskBadge level={result.risk.risk_level} /> : null}
            {result.risk && result.risk.category !== "unknown" ? <Badge tone="neutral">{categoryLabel(result.risk.category)}</Badge> : null}
            {result.detected_language ? (
              <Badge tone="neutral" icon="language">
                Detected: {languageName(result.detected_language)}
              </Badge>
            ) : null}
          </div>
          {result.risk && result.risk.signals.length > 0 ? <SignalList signals={result.risk.signals} /> : null}
          <p className="flex items-start gap-2 text-xs text-muted">
            <Icon name="info" size={14} className="mt-0.5 shrink-0" />
            Sparta never asks for or repeats protected information such as OTPs, PINs or passwords, whatever the caller says.
          </p>
        </div>
      ) : null}
    </SettingsCard>
  );
}
