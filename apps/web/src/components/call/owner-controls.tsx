"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { newIdempotencyKey } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { CallCapabilities, OwnerActionResult } from "@/lib/api/types";
import type { CallStatus } from "@/lib/api/enums";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, TextArea } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { useToast } from "@/components/ui/toast";

export interface OwnerControlsProps {
  callId: string;
  status: CallStatus;
  capabilities: CallCapabilities | null;
  /** True when Sparta is waiting for the owner's decision. */
  needsDecision?: boolean;
  blocked?: boolean;
  /** Called after any owner action succeeded (the live stream also delivers the events; this is the REST fallback). */
  onActed?: (result: OwnerActionResult | null) => void;
}

type Action = "takeover" | "continue" | "end" | "block";

/**
 * Take over / Let Sparta continue / End call / Block. Availability comes from CallDetail.capabilities: an unsupported
 * control is disabled and the provider's own note explains why. A 409 unsupported_by_provider is shown as-is, never as success.
 */
export function OwnerControls({ callId, status, capabilities, needsDecision, blocked, onActed }: OwnerControlsProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [blockOpen, setBlockOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const keys = useRef<Record<Action, string>>({
    takeover: newIdempotencyKey(),
    continue: newIdempotencyKey(),
    end: newIdempotencyKey(),
    block: newIdempotencyKey(),
  });

  const active = status === "active";
  const caps = capabilities;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
    void queryClient.invalidateQueries({ queryKey: qk.home });
  }

  function handleError(error: unknown) {
    if (isApiError(error) && error.kind === "unsupported_by_provider") setUnsupported(error.message);
  }

  const takeover = useMutation({
    mutationFn: () => api.calls.takeover(callId, { idempotencyKey: keys.current.takeover }),
    onSuccess: (result) => {
      setUnsupported(null);
      keys.current.takeover = newIdempotencyKey();
      toast.success(
        result.action.simulated ? "Takeover simulated: no real phone call was bridged to you." : "You took over the call.",
        { title: result.action.simulated ? "Simulated takeover" : "You are on the call" },
      );
      refresh();
      onActed?.(result);
    },
    onError: handleError,
  });

  const keepGoing = useMutation({
    mutationFn: () => api.calls.continueCall(callId, { idempotencyKey: keys.current.continue }),
    onSuccess: (result) => {
      setUnsupported(null);
      keys.current.continue = newIdempotencyKey();
      toast.success("Sparta will keep handling this call.", { title: "Sparta continues" });
      refresh();
      onActed?.(result);
    },
    onError: handleError,
  });

  const endCall = useMutation({
    mutationFn: () => api.calls.end(callId, { idempotencyKey: keys.current.end }),
    onSuccess: (result) => {
      setUnsupported(null);
      keys.current.end = newIdempotencyKey();
      toast.success("The call was ended.", { title: "Call ended" });
      refresh();
      onActed?.(result);
    },
    onError: handleError,
  });

  const block = useMutation({
    mutationFn: () => api.calls.block(callId, reason.trim() || undefined, { idempotencyKey: keys.current.block }),
    onSuccess: () => {
      keys.current.block = newIdempotencyKey();
      toast.success("This caller is blocked. You can undo it in the Safety Center.", { title: "Caller blocked" });
      setReason("");
      refresh();
      onActed?.(null);
    },
  });

  const canTakeOver = Boolean(caps?.can_take_over) && active;
  const canContinue = Boolean(caps?.can_continue) && active;
  const canEnd = Boolean(caps?.can_end) && active;
  const canBlock = (caps?.can_block ?? true) && !blocked;
  // A SIP-extension takeover rings a fixed extension on the local server: the provider's own note says so, and no owner phone number is involved.
  const sipExtension = caps?.takeover_via === "sip_extension";

  const reasonText = (supported: boolean | undefined, fallback: string): string | null => {
    if (!active) return "This call has ended.";
    if (!supported) return caps?.takeover_note ?? fallback;
    return null;
  };
  const takeoverReason = reasonText(caps?.can_take_over, "This provider cannot bridge the call to you.");
  const continueReason = reasonText(caps?.can_continue, "This provider cannot hand the call back to Sparta.");
  const endReason = reasonText(caps?.can_end, "This provider cannot end the call from here.");

  return (
    <div className="space-y-4" data-testid="owner-controls">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Button
          variant={needsDecision ? "primary" : "secondary"}
          icon="handoff"
          disabled={!canTakeOver}
          loading={takeover.isPending}
          onClick={() => takeover.mutate()}
          aria-describedby="owner-controls-notes"
          data-testid="action-takeover"
        >
          Take over
        </Button>
        <Button
          variant="secondary"
          icon="shield-check"
          disabled={!canContinue}
          loading={keepGoing.isPending}
          onClick={() => keepGoing.mutate()}
          aria-describedby="owner-controls-notes"
          data-testid="action-continue"
        >
          Let Sparta continue
        </Button>
        <Button
          variant="danger"
          icon="phone-end"
          disabled={!canEnd}
          onClick={() => setConfirmEnd(true)}
          aria-describedby="owner-controls-notes"
          data-testid="action-end"
        >
          End call
        </Button>
        <Button
          variant="secondary"
          icon="ban"
          disabled={!canBlock}
          onClick={() => setBlockOpen(true)}
          aria-describedby="owner-controls-notes"
          data-testid="action-block"
        >
          {blocked ? "Caller blocked" : "Block caller"}
        </Button>
      </div>

      <div id="owner-controls-notes" className="space-y-1.5 text-sm text-muted">
        {(caps?.simulated || sipExtension) && caps?.takeover_note ? (
          <p className="flex items-start gap-2" data-testid="takeover-note">
            {caps.simulated ? <Icon name="flask" size={16} className="mt-0.5 shrink-0 text-info" /> : <Icon name="handoff" size={16} className="mt-0.5 shrink-0" />}
            <span>{caps.takeover_note}</span>
          </p>
        ) : null}
        {caps?.audio_note ? (
          <p className="flex items-start gap-2" data-testid="audio-note">
            <Icon name="info" size={16} className="mt-0.5 shrink-0" />
            <span>{caps.audio_note}</span>
          </p>
        ) : null}
        {!canTakeOver && takeoverReason && !caps?.simulated ? (
          <p className="flex items-start gap-2" data-testid="takeover-unavailable">
            <Icon name="lock" size={16} className="mt-0.5 shrink-0" />
            <span>Take over unavailable: {takeoverReason}</span>
          </p>
        ) : null}
        {!active ? <p>These controls are off because the call has ended. You can still block the caller or give feedback.</p> : null}
        {active && !canContinue && continueReason ? <p>Let Sparta continue unavailable: {continueReason}</p> : null}
        {active && !canEnd && endReason ? <p>End call unavailable: {endReason}</p> : null}
      </div>

      {unsupported ? (
        <p role="alert" className="flex items-start gap-2 rounded-2xl border border-warning/40 bg-warning-bg px-3 py-2 text-sm text-fg" data-testid="unsupported-note">
          <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-warning" />
          <span>
            <strong className="font-semibold">Not done.</strong> {unsupported}
          </span>
        </p>
      ) : null}

      <ConfirmDialog
        open={confirmEnd}
        onClose={() => setConfirmEnd(false)}
        title="End this call?"
        description="Sparta will hang up on the caller. A summary is still saved."
        confirmLabel="End call"
        tone="danger"
        onConfirm={() => endCall.mutateAsync()}
      />

      <Dialog
        open={blockOpen}
        onClose={() => setBlockOpen(false)}
        title="Block this caller?"
        description="Future calls from this number are refused. Only the masked number is stored. You can unblock it in the Safety Center."
        footer={
          <>
            <Button variant="secondary" onClick={() => setBlockOpen(false)} data-autofocus>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={block.isPending}
              onClick={() => block.mutate(undefined, { onSuccess: () => setBlockOpen(false) })}
            >
              Block caller
            </Button>
          </>
        }
      >
        <Field label="Reason (optional)" hint="Shown only to you.">
          {(props) => <TextArea {...props} value={reason} maxLength={200} onChange={(event) => setReason(event.target.value)} rows={2} />}
        </Field>
      </Dialog>
    </div>
  );
}
