"use client";

import { useActiveCalls, useCallsInfinite } from "@/lib/query/hooks";
import { LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { PageHeader, Section } from "@/components/ui/layout";
import { CallLinkRow } from "@/components/call/call-row";

/** Entry point of the "Live call" tab: calls in progress, or a way to start a simulated one. */
export function LiveIndexScreen() {
  const active = useActiveCalls();
  const latest = useCallsInfinite({}, 1);
  const lastCall = latest.data?.pages[0]?.items[0];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Live call"
        description="Watch a call as it happens: who is calling, what is said in each language, and how risky it looks. Take over when Sparta asks."
      />

      {active.isPending ? <LoadingBlock label="Looking for calls in progress" lines={3} /> : null}
      {active.isError ? <ErrorState error={active.error} onRetry={() => void active.refetch()} title="Couldn't check for live calls" /> : null}

      {active.data && active.data.items.length > 0 ? (
        <Section title="In progress" description="Open one to follow it live.">
          <ul className="space-y-3" data-testid="active-calls">
            {active.data.items.map((call) => (
              <CallLinkRow key={call.id} call={call} href={`/live/${call.id}`} />
            ))}
          </ul>
        </Section>
      ) : null}

      {active.data && active.data.items.length === 0 ? (
        <EmptyState
          headingLevel={2}
          icon="wave"
          title="No call is active right now"
          description="When a call comes in, it appears here. You can also start a simulated call in the Simulator Lab to see the live view."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <LinkButton href="/simulator" variant="primary" icon="flask">
                Start a simulated call
              </LinkButton>
              {lastCall ? (
                <LinkButton href={`/calls/${lastCall.id}`} variant="secondary">
                  Open the latest call
                </LinkButton>
              ) : null}
            </div>
          }
        />
      ) : null}
    </div>
  );
}
