"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { useApi, useApiClient } from "../api/provider";
import { toWebSocketBase } from "../api/config";
import type { TurnResult } from "../api/types";
import { isEndState } from "../call-state";
import { LiveConnection } from "./socket";
import { initialLiveState, liveReducer, staleEscalationId, type LiveCallState } from "./reducer";

export interface UseLiveCallOptions {
  /** Set false to render a call from REST data only (no WebSocket). */
  enabled?: boolean;
}

export interface UseLiveCall {
  state: LiveCallState;
  /** Fold a REST TurnResult into the model (idempotent with the matching WebSocket events). */
  applyTurnResult: (result: TurnResult) => void;
  /** Re-fetch the call from REST and replace the model. */
  refresh: () => Promise<void>;
  /** Skip the reconnect backoff wait. */
  reconnect: () => void;
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

/**
 * Live view of one call: REST snapshot + WebSocket events folded by `liveReducer`.
 * Mount it with `key={callId}` so a different call starts from a clean model.
 */
export function useLiveCall(callId: string | null, { enabled = true }: UseLiveCallOptions = {}): UseLiveCall {
  const api = useApi();
  const client = useApiClient();
  const [state, dispatch] = useReducer(liveReducer, callId, initialLiveState);

  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  });
  const connectionRef = useRef<LiveConnection | null>(null);

  // Initial snapshot over REST so the screen renders even when the socket is slow or blocked.
  useEffect(() => {
    if (!callId) return;
    const controller = new AbortController();
    api.calls
      .get(callId, { signal: controller.signal })
      .then((call) => dispatch({ type: "snapshot", call, at: Date.now() }))
      .catch(() => {
        /* the caller renders the query error; the socket may still deliver a snapshot */
      });
    return () => controller.abort();
  }, [api, callId]);

  useEffect(() => {
    if (!callId || !enabled) return;
    const controller = new AbortController();
    let hasOpened = false;

    const backfillFrom = async (afterSeq: number) => {
      try {
        const events = await api.calls.events(callId, afterSeq, { signal: controller.signal });
        if (!controller.signal.aborted) dispatch({ type: "backfill", events, at: Date.now() });
      } catch {
        /* a later gap or reconnect retries; the snapshot keeps the model correct meanwhile */
      }
    };

    const connection = new LiveConnection({
      callId,
      getTicket: (id) => api.live.ticket(id ?? undefined),
      wsBase: toWebSocketBase(client.baseUrl),
      onEvent: (event) => dispatch({ type: "event", event, at: Date.now() }),
      onStatus: (status, info) => {
        dispatch({ type: "connection", status, attempt: info.attempt });
        if (status === "open") {
          // After a reconnect, fill whatever was missed while offline (the server starts with a fresh snapshot).
          if (hasOpened) void backfillFrom(stateRef.current.lastSeq);
          hasOpened = true;
        }
      },
      shouldReconnect: () => !isEndState(stateRef.current.state) && stateRef.current.status === "active",
    });
    connectionRef.current = connection;
    connection.start();

    const onOnline = () => connection.reconnectNow();
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("online", onOnline);
      controller.abort();
      connection.stop();
      connectionRef.current = null;
    };
  }, [api, client, callId, enabled]);

  // Gap handling: a seq jump or `stream.resync` holds live events until the persisted log fills the gap.
  const { gapAfterSeq, resyncCount } = state;
  useEffect(() => {
    if (!callId || gapAfterSeq === null) return;
    const controller = new AbortController();
    (async () => {
      for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
        try {
          const events = await api.calls.events(callId, gapAfterSeq, { signal: controller.signal });
          if (!controller.signal.aborted) dispatch({ type: "backfill", events, at: Date.now() });
          return;
        } catch {
          await sleep(400 * 2 ** attempt, controller.signal);
        }
      }
      if (controller.signal.aborted) return;
      try {
        const call = await api.calls.get(callId, { signal: controller.signal });
        dispatch({ type: "snapshot", call, at: Date.now(), force: true });
      } catch {
        /* still offline: the reconnect logic keeps trying */
      }
    })();
    return () => controller.abort();
  }, [api, callId, gapAfterSeq, resyncCount]);

  // An escalation can end without an event of its own (the owner did not answer in time): ask REST for its real status.
  const staleEscalation = staleEscalationId(state);
  useEffect(() => {
    if (!callId || !staleEscalation) return;
    const controller = new AbortController();
    (async () => {
      for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
        try {
          const call = await api.calls.get(callId, { signal: controller.signal });
          if (controller.signal.aborted) return;
          dispatch({ type: "escalations", escalations: call.escalations, ownerActions: call.owner_actions });
          if (call.escalations.every((escalation) => escalation.status !== "requested")) return;
        } catch {
          /* try again; the model keeps showing the last known state meanwhile */
        }
        await sleep(400 * 2 ** attempt, controller.signal);
      }
    })();
    return () => controller.abort();
  }, [api, callId, staleEscalation]);

  const applyTurnResult = useCallback((result: TurnResult) => dispatch({ type: "turn-result", result, at: Date.now() }), []);

  const refresh = useCallback(async () => {
    if (!callId) return;
    const call = await api.calls.get(callId);
    dispatch({ type: "snapshot", call, at: Date.now(), force: true });
  }, [api, callId]);

  const reconnect = useCallback(() => connectionRef.current?.reconnectNow(), []);

  return { state, applyTurnResult, refresh, reconnect };
}
