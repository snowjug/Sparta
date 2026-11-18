"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { NETWORK_PROFILES, type NetworkProfile } from "@/lib/api/enums";
import { newIdempotencyKey } from "@/lib/api/client";
import { useApi } from "@/lib/api/provider";
import type { ScenarioSummary } from "@/lib/api/types";
import { actionLabel } from "@/lib/labels";
import { languageName, profileLabel } from "@/lib/language";
import { useLiveCall } from "@/lib/live/use-live-call";
import { useActiveCalls, useScenarios, useSystemStatus } from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { cancelBrowserSpeech, isSpeechSynthesisSupported, speakWithBrowser } from "@/lib/speech/tts";
import { STORAGE_KEYS } from "@/lib/storage";
import { useStoredBoolean } from "@/lib/use-stored";
import { Badge } from "@/components/ui/badge";
import { Button, LinkButton } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Field, Select, Switch, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { Card, Disclosure, PageHeader, Section } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import { LanguageChip, StateBadge } from "@/components/call/badges";
import { DiagnosticsPanel } from "@/components/call/diagnostics";
import { LiveVoiceStage } from "@/components/call/live-voice-stage";
import { OwnerControls } from "@/components/call/owner-controls";
import { RiskPanel } from "@/components/call/risk-panel";
import { StateStepper } from "@/components/call/state-stepper";
import { Transcript } from "@/components/call/transcript";
import { SimulationBadge } from "@/components/shell/provider-badge";
import { CallTimer, ConnectionPill } from "@/features/live/live-call-screen";
import { useCallActions } from "@/features/history/use-call-actions";
import { CallerInput } from "./caller-input";
import { EventLog } from "./event-log";
import { ProviderList } from "./provider-list";
import { ReplayPanel } from "./replay-panel";
import { ScenarioBuilder } from "./scenario-builder";

const NETWORK_COPY: Record<NetworkProfile, { label: string; description: string }> = {
  ideal: { label: "Ideal", description: "No extra delay." },
  mobile_4g: { label: "Mobile 4G", description: "Adds typical mobile latency." },
  congested: { label: "Congested", description: "Adds heavy, jittery latency." },
};

/** Console for one simulated call: live stage and transcript, caller inputs, owner controls, event log, diagnostics. */
function LabConsole({ callId, language, maxAudioBytes, onNewCall }: { callId: string; language: string; maxAudioBytes: number; onNewCall: () => void }) {
  const { state: live, applyTurnResult, reconnect } = useLiveCall(callId);
  const { downloadReport } = useCallActions();
  const [hear, setHear] = useStoredBoolean(STORAGE_KEYS.labHear, false);
  const [showTranslation, setShowTranslation] = useStoredBoolean(STORAGE_KEYS.showTranslation, false);
  const reader = useRef<(() => ArrayLike<number> | null) | null>(null);
  const setReader = useCallback((next: (() => ArrayLike<number> | null) | null) => {
    reader.current = next;
  }, []);
  const readMicLevels = useCallback(() => reader.current?.() ?? null, []);
  const cancelSpeech = useRef<(() => void) | null>(null);

  const call = live.call;
  const active = live.status === "active";
  const speaking = live.assistant.speaking;
  const interruptedAt = live.assistant.interrupted?.at ?? 0;
  const browserTts = typeof window !== "undefined" && isSpeechSynthesisSupported();

  // Optional browser voice: speaks each assistant reply as it starts. It never drives the visualisation (that follows
  // the server's est_duration_ms) and it is not the production voice.
  useEffect(() => {
    if (!hear || !speaking) return;
    cancelSpeech.current?.();
    cancelSpeech.current = speakWithBrowser(speaking.text, speaking.locale || "en-IN", 1);
  }, [hear, speaking]);

  useEffect(() => {
    if (interruptedAt) {
      cancelSpeech.current?.();
      cancelSpeech.current = null;
    }
  }, [interruptedAt]);

  useEffect(() => () => cancelBrowserSpeech(), []);
  useEffect(() => {
    if (!hear) {
      cancelSpeech.current?.();
      cancelSpeech.current = null;
    }
  }, [hear]);

  return (
    <div className="space-y-6" data-testid="lab-console" data-call-id={callId} data-status={live.status} data-state={live.state ?? ""}>
      <Card className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <h2 className="text-xl font-semibold tracking-tight text-fg" data-testid="console-title">
              {call?.caller_display ?? "Simulated call"}
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <SimulationBadge simulated={call?.simulated ?? true} provider={call?.provider} />
              <StateBadge state={live.state ?? call?.state ?? null} />
              <ConnectionPill live={live} onReconnect={reconnect} />
              <span className="text-sm text-muted">
                <CallTimer call={call} live={live} />
              </span>
              {live.language.code ? <LanguageChip code={live.language.code} variant={live.language.profile} confidence={live.language.confidence} /> : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {!active ? (
              <>
                <LinkButton href={`/calls/${callId}`} variant="primary" size="sm" trailingIcon="arrow-right" data-testid="open-call-detail">
                  Open call detail
                </LinkButton>
                <Button variant="secondary" size="sm" icon="refresh" onClick={onNewCall} data-testid="new-call">
                  Start another call
                </Button>
              </>
            ) : null}
            <Button variant="secondary" size="sm" icon="download" loading={downloadReport.isPending} onClick={() => downloadReport.mutate(callId)} data-testid="lab-report">
              Sanitized diagnostic report
            </Button>
          </div>
        </div>

        {!active && (live.summary ?? call?.summary) ? (
          <p className="rounded-2xl bg-raised px-4 py-3 text-base text-fg" data-testid="lab-summary">
            <span className="font-semibold">Summary: </span>
            {(live.summary ?? call?.summary)?.text}
          </p>
        ) : null}

        <div className="grid items-center gap-6 md:grid-cols-[minmax(0,18rem)_1fr]">
          <LiveVoiceStage live={live} readMicLevels={readMicLevels} />
          <div className="space-y-5">
            <StateStepper state={live.state} status={live.status} />
            <div className="rounded-2xl border border-line bg-raised p-3">
              <Switch
                checked={hear}
                onChange={setHear}
                disabled={!browserTts}
                label="Hear the assistant (BROWSER voice)"
                description={
                  browserTts
                    ? "Speaks each reply with your browser's built-in voice. This is not the production voice, and it does not drive the animation."
                    : "This browser has no speech synthesis."
                }
              />
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Section title="Caller" description="Play the caller: type, speak, upload a clip, interrupt, or stay silent.">
          <Card>
            <CallerInput
              callId={callId}
              language={language}
              active={active}
              speaking={speaking}
              maxAudioBytes={maxAudioBytes}
              onTurnResult={applyTurnResult}
              onLevelsReader={setReader}
            />
          </Card>
        </Section>

        <div className="space-y-6">
          <Section
            title="Live transcript"
            actions={
              <div className="w-60 max-w-full">
                <Switch checked={showTranslation} onChange={setShowTranslation} label="Show English translation" />
              </div>
            }
          >
            <Card className="p-4">
              <Transcript
                live
                turns={live.turns}
                partial={live.partial}
                signals={live.risk?.signals ?? []}
                showTranslation={showTranslation}
                empty={<p className="text-sm text-muted">Waiting for the first words.</p>}
              />
            </Card>
          </Section>
          <Section title="Your controls (owner simulation)">
            <Card>
              <OwnerControls callId={callId} status={live.status} capabilities={call?.capabilities ?? null} needsDecision={live.escalation?.status === "requested"} blocked={call?.blocked} />
            </Card>
          </Section>
        </div>
      </div>

      <Section title="Risk and evidence">
        <Card>
          <RiskPanel risk={live.risk} fallbackLevel={call?.risk_level} fallbackScore={call?.risk_score} fallbackConfidence={call?.confidence} />
        </Card>
      </Section>

      <Disclosure summary="Event log" className="bg-surface" summaryClassName="text-base">
        <EventLog events={live.events} total={live.eventCount} callId={callId} />
      </Disclosure>
      <DiagnosticsPanel live={live} call={call} onReconnect={reconnect} />
    </div>
  );
}

function ScenarioOption({ scenario, checked, onSelect }: { scenario: ScenarioSummary; checked: boolean; onSelect: () => void }) {
  return (
    <label className="relative block cursor-pointer" data-testid="scenario-option" data-scenario-id={scenario.id}>
      <input type="radio" name="scenario" value={scenario.id} checked={checked} onChange={onSelect} className="peer sr-only" />
      <span className="block rounded-2xl border border-line-strong bg-surface p-3 transition-colors hover:bg-raised peer-checked:border-accent peer-checked:bg-accent-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus">
        <span className="flex items-start justify-between gap-2">
          <span className="text-sm font-semibold text-fg">{scenario.title}</span>
          <Icon name="check" size={16} className={checked ? "shrink-0 text-accent" : "shrink-0 text-transparent"} />
        </span>
        {scenario.description ? <span className="mt-0.5 block text-sm text-muted">{scenario.description}</span> : null}
        <span className="mt-2 flex flex-wrap items-center gap-1.5">
          {scenario.custom ? <Badge tone="accent">Yours</Badge> : null}
          <Badge tone="neutral" icon="language">
            {profileLabel(scenario.language_profile)}
          </Badge>
          <Badge tone="neutral">{scenario.turn_count} turn{scenario.turn_count === 1 ? "" : "s"}</Badge>
          {scenario.expected_action ? <Badge tone="neutral">Expected: {actionLabel(scenario.expected_action)}</Badge> : null}
        </span>
      </span>
    </label>
  );
}

export default function LabScreen() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: status } = useSystemStatus();
  const scenarios = useScenarios();
  const active = useActiveCalls();
  const [scenarioId, setScenarioId] = useState("");
  const [language, setLanguage] = useState("auto");
  const [network, setNetwork] = useState<NetworkProfile>("ideal");
  const [label, setLabel] = useState("");
  const [autoTimers, setAutoTimers] = useState(false);
  const [autoplay, setAutoplay] = useState(false);
  const [callId, setCallId] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());
  const consoleAnchor = useRef<HTMLDivElement>(null);

  const selected = scenarios.data?.find((scenario) => scenario.id === scenarioId) ?? null;
  const supportedLanguages = (status?.languages ?? []).filter((l) => l.status === "supported").map((l) => l.code);
  const languageChoices = ["auto", ...(supportedLanguages.length > 0 ? supportedLanguages : ["en-IN", "hi-IN", "kn-IN"])];
  const inProgress = active.data?.items.find((item) => item.simulated && item.status === "active") ?? null;
  const currentActive = callId ? Boolean(active.data?.items.some((item) => item.id === callId)) : false;

  const start = useMutation({
    mutationFn: () =>
      api.simulator.startCall(
        {
          scenario_id: scenarioId || undefined,
          autoplay: Boolean(scenarioId) && autoplay,
          language_mode: language,
          network_profile: network,
          caller_label: label.trim() || undefined,
          silence_timers: autoTimers ? "preferences" : "off",
        },
        { idempotencyKey: key.current },
      ),
    onSuccess: (call) => {
      key.current = newIdempotencyKey();
      setCallId(call.id);
      void queryClient.invalidateQueries({ queryKey: qk.home });
      void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
      toast.success(autoplay && scenarioId ? "Simulated call started. The scripted caller is speaking now." : "Simulated call started. Play the caller below.", { title: "Call started" });
      requestAnimationFrame(() => consoleAnchor.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    },
  });

  const setup = (
    <div className="space-y-8">
      <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
        <Section title="1 · Choose a call">
            <Card className="space-y-5">
              {scenarios.isPending ? <LoadingBlock label="Loading scenarios" lines={4} /> : null}
              {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} title="Couldn't load the scenarios" /> : null}
              {scenarios.data ? (
                <fieldset>
                  <legend className="mb-2 text-sm font-semibold text-fg">Scenario</legend>
                  <div className="sp-scroll max-h-[26rem] space-y-2 overflow-y-auto pr-1" role="radiogroup" aria-label="Scenario" data-testid="scenario-list">
                    <label className="relative block cursor-pointer" data-testid="scenario-option" data-scenario-id="">
                      <input type="radio" name="scenario" value="" checked={scenarioId === ""} onChange={() => setScenarioId("")} className="peer sr-only" />
                      <span className="block rounded-2xl border border-line-strong bg-surface p-3 transition-colors hover:bg-raised peer-checked:border-accent peer-checked:bg-accent-soft peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus">
                        <span className="text-sm font-semibold text-fg">Free play</span>
                        <span className="mt-0.5 block text-sm text-muted">No script. You type, speak or upload what the caller says.</span>
                      </span>
                    </label>
                    {scenarios.data.map((scenario) => (
                      <ScenarioOption key={scenario.id} scenario={scenario} checked={scenarioId === scenario.id} onSelect={() => setScenarioId(scenario.id)} />
                    ))}
                  </div>
                </fieldset>
              ) : null}
            </Card>
          </Section>

          <Section title="2 · Settings">
            <Card className="space-y-4">
              <Field label="Caller language" hint="“Auto” detects the language of every turn. Pick one to force it (also used by the microphone).">
                {(props) => (
                  <Select {...props} value={language} onChange={(event) => setLanguage(event.target.value)} data-testid="language-select">
                    {languageChoices.map((code) => (
                      <option key={code} value={code}>
                        {languageName(code)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Network profile" hint={NETWORK_COPY[network].description + " Added latency is simulated and marked as such in diagnostics."}>
                {(props) => (
                  <Select {...props} value={network} onChange={(event) => setNetwork(event.target.value as NetworkProfile)} data-testid="network-select">
                    {NETWORK_PROFILES.map((value) => (
                      <option key={value} value={value}>
                        {NETWORK_COPY[value].label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Caller label (optional)" hint="How the caller appears in your history. Not a real number.">
                {(props) => <TextInput {...props} value={label} maxLength={80} onChange={(event) => setLabel(event.target.value)} autoComplete="off" />}
              </Field>
              <Switch
                checked={autoplay}
                onChange={setAutoplay}
                disabled={!scenarioId}
                label="Play the scripted caller automatically"
                description={scenarioId ? "The server plays the scenario in real time, with its pauses." : "Choose a scenario first."}
              />
              <Switch
                checked={autoTimers}
                onChange={setAutoTimers}
                label="Automatic silence timeouts"
                description="On: the call closes if the caller is silent for your two silence timeouts (8 s each by default). Off is easier for experiments."
              />
              <div className="space-y-2">
                <Button
                  variant="primary"
                  size="lg"
                  fullWidth
                  icon="play"
                  loading={start.isPending}
                  disabled={currentActive}
                  onClick={() => start.mutate()}
                  aria-describedby="start-hint"
                  data-testid="start-call"
                >
                  Start simulated call
                </Button>
                <p id="start-hint" className="text-sm text-muted">
                  {currentActive ? "A call is in progress. End it (or let it finish) before starting another." : "Starts a new simulated call and opens the live console."}
                </p>
                {inProgress && !callId ? (
                  <Button variant="secondary" fullWidth onClick={() => setCallId(inProgress.id)}>
                    Resume the call in progress ({inProgress.caller_display})
                  </Button>
                ) : null}
              </div>
            </Card>
          </Section>
        </div>

        <div className="space-y-4">
          <Disclosure summary="Custom scenario builder" className="bg-surface" summaryClassName="text-base">
            <ScenarioBuilder onCreated={(scenario) => setScenarioId(scenario.id)} />
          </Disclosure>
          <Disclosure summary="Deterministic replay" className="bg-surface" summaryClassName="text-base">
            <ReplayPanel scenario={selected} language={language} network={network} />
          </Disclosure>
          <Disclosure summary="Provider status" className="bg-surface" summaryClassName="text-base">
            <ProviderList />
          </Disclosure>
        </div>
      </div>
  );

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Developer tools"
        title="Simulator Lab"
        description="Play the caller to test Sparta end to end, with scripted scenarios, your own words, the browser microphone or an audio clip. Everything here is simulated: no real phone call is made."
        actions={<SimulationBadge simulated />}
      />

      {callId ? (
        <>
          <div ref={consoleAnchor} className="min-w-0 scroll-mt-24">
            <LabConsole key={callId} callId={callId} language={language} maxAudioBytes={status?.limits.max_audio_bytes ?? 8_000_000} onNewCall={() => setCallId(null)} />
          </div>
          <Disclosure summary="Start another call, change the settings, or build a scenario" className="bg-surface" summaryClassName="text-base">
            {setup}
          </Disclosure>
        </>
      ) : (
        setup
      )}
    </div>
  );
}

export { LabScreen };
