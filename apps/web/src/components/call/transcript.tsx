"use client";

import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { CallTurn, RiskSignal } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import { splitByExcerpts } from "@/lib/highlight";
import { htmlLang, languageChanges, languageName, turnLanguage, variantLabel, variantOf } from "@/lib/language";
import { signalLabel } from "@/lib/labels";
import { severityTone } from "@/lib/risk";
import type { PartialInfo } from "@/lib/live/reducer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { LanguageChip } from "./badges";

const SPEAKER_LABEL: Record<string, string> = {
  caller: "Caller",
  assistant: "Sparta · AI assistant",
  owner: "You",
  system: "System",
};

const SOURCE_LABEL: Record<string, string> = {
  browser_stt: "browser speech recognition",
  provider_stt: "speech recognition",
  uploaded_audio: "uploaded audio",
  scripted: "scripted scenario",
};

function Highlighted({ text, excerpts }: { text: string; excerpts: string[] }) {
  const segments = useMemo(() => splitByExcerpts(text, excerpts), [text, excerpts]);
  return (
    <>
      {segments.map((segment, index) =>
        segment.mark ? (
          <mark key={index} data-testid="evidence-mark" className="rounded bg-warning-bg px-0.5 text-fg underline decoration-warning decoration-2 underline-offset-4">
            {segment.text}
          </mark>
        ) : (
          <Fragment key={index}>{segment.text}</Fragment>
        ),
      )}
    </>
  );
}

export function TurnBubble({
  turn,
  signals,
  showTranslation,
  lazy = false,
}: {
  turn: CallTurn;
  signals: RiskSignal[];
  showTranslation: boolean;
  /** Older turns are laid out lazily (content-visibility) so long transcripts stay cheap. */
  lazy?: boolean;
}) {
  const fromCaller = turn.speaker === "caller";
  const fromAssistant = turn.speaker === "assistant";
  const language = turnLanguage(turn);
  const excerpts = useMemo(() => signals.map((s) => s.evidence_excerpt).filter((v): v is string => Boolean(v)), [signals]);
  const nonEnglish = turn.language && !turn.language.toLowerCase().startsWith("en");

  return (
    <li
      id={`turn-${turn.id}`}
      data-testid="turn"
      data-speaker={turn.speaker}
      data-language={turn.language ?? ""}
      className={cn("flex scroll-mt-24", fromAssistant ? "justify-end" : "justify-start", lazy && "sp-lazy-turn")}
    >
      <div
        className={cn(
          "max-w-[92%] rounded-3xl border px-4 py-3 sm:max-w-[80%]",
          fromAssistant ? "rounded-br-lg border-accent/30 bg-accent-soft" : "rounded-bl-lg border-line bg-raised",
          signals.length > 0 && "border-l-4 border-l-warning",
        )}
      >
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">{SPEAKER_LABEL[turn.speaker] ?? turn.speaker}</span>
          <span className="text-xs tabular-nums text-muted">{formatTime(turn.created_at)}</span>
          {turn.language ? <LanguageChip code={turn.language} variant={variantLabel(variantOf(turn)) ? variantOf(turn) : null} confidence={fromCaller ? turn.language_confidence : null} /> : null}
          {turn.interrupted ? (
            <Badge tone="warning" icon="bolt">
              Interrupted{turn.spoken_fraction !== null ? ` · ${Math.round(turn.spoken_fraction * 100)}% spoken` : ""}
            </Badge>
          ) : null}
        </div>
        <p lang={htmlLang(turn.language)} className="whitespace-pre-wrap break-words text-base text-fg">
          <Highlighted text={turn.text} excerpts={excerpts} />
        </p>
        {showTranslation && nonEnglish ? (
          <p className="mt-2 border-t border-line pt-2 text-sm text-muted" data-testid="translation">
            <span className="font-semibold text-fg">English: </span>
            {turn.translation ? turn.translation : <em>No translation available for this turn.</em>}
          </p>
        ) : null}
        {signals.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Evidence in this turn">
            {signals.map((signal, index) => (
              <Badge key={`${signal.code}-${index}`} tone={severityTone(signal.severity, signal.kind)} icon={signal.kind === "legitimate" ? "check" : "alert"}>
                {signalLabel(signal.code)}
              </Badge>
            ))}
          </div>
        ) : null}
        {turn.source !== "typed" && turn.source !== "assistant" && turn.source !== "system" ? (
          <p className="mt-1.5 text-xs text-muted">
            via {SOURCE_LABEL[turn.source] ?? turn.source}
            {fromCaller && turn.confidence !== null ? ` · recognised with ${Math.round(turn.confidence * 100)}% confidence` : ""}
          </p>
        ) : null}
        <span className="sr-only">
          {language.name}
          {language.variant ? `, ${language.variant}` : ""}
        </span>
      </div>
    </li>
  );
}

function LanguageChangeMarker({ from, to, variant }: { from: string; to: string; variant: string | null }) {
  return (
    <li data-testid="language-change" className="flex items-center gap-3 py-1 text-xs font-medium text-muted" aria-label={`Language changed from ${languageName(from)} to ${languageName(to)}`}>
      <span aria-hidden="true" className="h-px flex-1 bg-line" />
      <span className="inline-flex items-center gap-1.5">
        <Icon name="language" size={14} />
        Language changed: {languageName(from)} → {languageName(to)}
        {variant ? ` (${variant})` : ""}
      </span>
      <span aria-hidden="true" className="h-px flex-1 bg-line" />
    </li>
  );
}

function PartialBubble({ partial }: { partial: PartialInfo }) {
  const fromAssistant = partial.speaker === "assistant";
  return (
    <li data-testid="partial-turn" className={cn("flex", fromAssistant ? "justify-end" : "justify-start")}>
      <div className="max-w-[92%] rounded-3xl border border-dashed border-line-strong bg-surface px-4 py-3 sm:max-w-[80%]">
        <p className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
          {SPEAKER_LABEL[partial.speaker] ?? partial.speaker}
          <span className="inline-flex items-center gap-1 normal-case tracking-normal">
            <span aria-hidden="true" className="size-1.5 animate-live-dot rounded-full bg-accent" />
            hearing…
          </span>
        </p>
        <p lang={htmlLang(partial.language)} className="whitespace-pre-wrap break-words text-base italic text-fg" aria-live="off">
          {partial.text}
        </p>
      </div>
    </li>
  );
}

export interface TranscriptProps {
  turns: CallTurn[];
  partial?: PartialInfo | null;
  signals?: RiskSignal[];
  showTranslation: boolean;
  /** Live mode: announces new turns politely and keeps the newest turn in view. */
  live?: boolean;
  maxRendered?: number;
  empty?: ReactNode;
  className?: string;
  label?: string;
}

export function Transcript({ turns, partial = null, signals = [], showTranslation, live = false, maxRendered = 200, empty, className, label = "Transcript" }: TranscriptProps) {
  const [expanded, setExpanded] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [unseen, setUnseen] = useState(false);

  const visibleTurns = expanded || turns.length <= maxRendered ? turns : turns.slice(turns.length - maxRendered);
  const hidden = turns.length - visibleTurns.length;
  const changes = useMemo(() => new Map(languageChanges(turns).map((change) => [change.beforeTurnId, change])), [turns]);
  const byTurn = useMemo(() => {
    const map = new Map<string, RiskSignal[]>();
    for (const signal of signals) {
      for (const id of signal.evidence_turn_ids) map.set(id, [...(map.get(id) ?? []), signal]);
    }
    return map;
  }, [signals]);

  // Follow the conversation unless the owner scrolled up to read earlier turns.
  const turnCount = turns.length;
  const partialText = partial?.text ?? null;
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!live || !element) return;
    if (stick.current) element.scrollTop = element.scrollHeight;
  }, [live, turnCount, partialText]);
  useEffect(() => {
    if (live && !stick.current) {
      const id = requestAnimationFrame(() => setUnseen(true));
      return () => cancelAnimationFrame(id);
    }
  }, [live, turnCount]);

  function onScroll() {
    const element = scroller.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
    stick.current = nearBottom;
    if (nearBottom) setUnseen(false);
  }

  const list = (
    <ol className="space-y-3" aria-label={label}>
      {hidden > 0 ? (
        <li className="flex justify-center">
          <Button variant="secondary" size="sm" onClick={() => setExpanded(true)}>
            Show {hidden} earlier turn{hidden === 1 ? "" : "s"}
          </Button>
        </li>
      ) : null}
      {visibleTurns.map((turn, index) => {
        const change = changes.get(turn.id);
        return (
          <Fragment key={turn.id}>
            {change ? <LanguageChangeMarker from={change.from} to={change.to} variant={change.variant} /> : null}
            <TurnBubble turn={turn} signals={byTurn.get(turn.id) ?? []} showTranslation={showTranslation} lazy={index < visibleTurns.length - 12} />
          </Fragment>
        );
      })}
      {partial ? <PartialBubble partial={partial} /> : null}
    </ol>
  );

  if (turns.length === 0 && !partial) {
    return <div className={className}>{empty ?? <p className="text-sm text-muted">No transcript for this call.</p>}</div>;
  }

  if (!live) return <div className={className}>{list}</div>;

  return (
    <div className={cn("relative", className)}>
      <div
        ref={scroller}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label={`${label} (live)`}
        tabIndex={0}
        className="sp-scroll max-h-[min(34rem,60dvh)] min-h-48 overflow-y-auto rounded-2xl pr-1"
        data-testid="live-transcript"
      >
        {list}
      </div>
      {unseen ? (
        <Button
          variant="primary"
          size="sm"
          icon="chevron-down"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-card"
          onClick={() => {
            stick.current = true;
            setUnseen(false);
            const element = scroller.current;
            if (element) element.scrollTop = element.scrollHeight;
          }}
        >
          Jump to latest
        </Button>
      ) : null}
    </div>
  );
}
