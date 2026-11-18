"use client";

import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/lib/api/provider";
import { formatDuration } from "@/lib/format";
import { htmlLang, languageName } from "@/lib/language";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";

/** The disclosure the API produces for the saved profile (preview endpoint). `draftName` only labels a pending change. */
export function DisclosurePreviewBlock({ draftName }: { draftName: string }) {
  const api = useApi();
  const query = useQuery({
    queryKey: ["assistant", "preview", "onboarding"],
    queryFn: ({ signal }) => api.assistant.preview({ language: "auto" }, { signal }),
    staleTime: 10_000,
  });
  const plan = query.data?.disclosure;
  return (
    <div>
      {query.isPending ? <LoadingBlock label="Loading preview" lines={2} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't preview the disclosure" /> : null}
      {plan ? (
        <figure className="rounded-3xl border border-line bg-raised p-5" data-testid="onboarding-disclosure">
          <figcaption className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-accent">What callers hear first</figcaption>
          <blockquote lang={htmlLang(plan.locale)} className="text-pretty text-xl text-fg">
            {plan.text}
          </blockquote>
          <p className="mt-3 text-sm text-muted">
            {languageName(plan.locale)} · about <span className="tabular-nums">{formatDuration(plan.est_duration_ms)}</span> to say
            {draftName.trim() ? ". The name updates after you continue." : ""}
          </p>
        </figure>
      ) : null}
    </div>
  );
}
