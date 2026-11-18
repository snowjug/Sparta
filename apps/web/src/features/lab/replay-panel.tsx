"use client";

import { useMutation } from "@tanstack/react-query";
import type { NetworkProfile } from "@/lib/api/enums";
import { useApi } from "@/lib/api/provider";
import type { ReplayResult, ScenarioSummary } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";

interface ReplayRun {
  result: ReplayResult;
}

/** Deterministic replay: the server runs a scenario on a virtual clock with no randomness, so equal input => equal checksum. */
export function ReplayPanel({ scenario, language, network }: { scenario: ScenarioSummary | null; language: string; network: NetworkProfile }) {
  const api = useApi();
  const replay = useMutation({
    mutationFn: async (times: 1 | 2): Promise<ReplayRun[]> => {
      const runs: ReplayRun[] = [];
      for (let i = 0; i < times; i += 1) {
        const result = await api.simulator.replay({ scenario_id: scenario!.id, language_mode: language, network_profile: network });
        runs.push({ result });
      }
      return runs;
    },
  });
  const runs = replay.data;
  const equal = runs && runs.length === 2 ? runs[0]!.result.checksum === runs[1]!.result.checksum : null;

  return (
    <div className="space-y-4" data-testid="replay-panel">
      <p className="text-sm text-muted">
        Replays the selected scenario instantly on a virtual clock, with no randomness and no real waiting. Running it twice must give the same checksum.
        {scenario ? null : " Pick a scenario above first."}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" icon="play" disabled={!scenario} loading={replay.isPending && replay.variables === 1} onClick={() => replay.mutate(1)} data-testid="replay-once">
          Replay once
        </Button>
        <Button variant="secondary" icon="refresh" disabled={!scenario} loading={replay.isPending && replay.variables === 2} onClick={() => replay.mutate(2)} data-testid="replay-twice">
          Run twice and compare
        </Button>
      </div>

      {runs ? (
        <div className="space-y-3 rounded-2xl border border-line bg-raised p-4" aria-live="polite" data-testid="replay-result">
          {equal !== null ? (
            <Badge tone={equal ? "success" : "danger"} icon={equal ? "check" : "alert"} data-testid="replay-equality">
              {equal ? "Checksums are identical" : "Checksums differ"}
            </Badge>
          ) : null}
          <ul className="space-y-3">
            {runs.map(({ result }, index) => (
              <li key={index} className="space-y-1 text-sm">
                <p className="font-semibold text-fg">Run {index + 1}</p>
                <p className="flex flex-wrap items-center gap-2 text-muted">
                  <span>Checksum</span>
                  <code className="break-all rounded-lg bg-sunken px-2 py-0.5 font-mono text-xs text-fg" data-testid={`checksum-${index + 1}`}>
                    {result.checksum}
                  </code>
                  <CopyButton text={result.checksum} label="Copy" />
                </p>
                <p className="text-muted">
                  {result.events.length} events · ends in <span className="font-medium text-fg">{result.call.state}</span> · risk <span className="font-medium text-fg">{result.call.risk_level}</span>
                </p>
                <p className="flex items-start gap-1.5 text-xs text-muted">
                  <Icon name="info" size={14} className="mt-0.5 shrink-0" />
                  Covers: {result.checksum_covers}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
