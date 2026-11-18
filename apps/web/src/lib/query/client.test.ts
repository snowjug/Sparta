import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { createQueryClient, isRetryable } from "./client";
import { qk } from "./keys";

describe("query client", () => {
  it("refreshes the audit log after any successful change, but not after a failed one", async () => {
    const client = createQueryClient({ retry: false });
    client.setQueryData(qk.audit(50), []);
    const spy = vi.spyOn(client, "invalidateQueries");

    await client.getMutationCache().build(client, { mutationFn: async () => "ok" }).execute(undefined);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["safety", "audit"] });
    expect(client.getQueryState(qk.audit(50))?.isInvalidated).toBe(true);

    spy.mockClear();
    await client.getMutationCache().build(client, { mutationFn: async () => Promise.reject(new Error("nope")) }).execute(undefined).catch(() => undefined);
    expect(spy).not.toHaveBeenCalled();
  });

  it("reports mutation failures to the toast hook unless the mutation is silent", async () => {
    const onMutationError = vi.fn();
    const client = createQueryClient({ retry: false, onMutationError });
    const fail = () => Promise.reject(new Error("boom"));
    await client.getMutationCache().build(client, { mutationFn: fail }).execute(undefined).catch(() => undefined);
    await client.getMutationCache().build(client, { mutationFn: fail, meta: { silent: true } }).execute(undefined).catch(() => undefined);
    expect(onMutationError).toHaveBeenCalledTimes(1);
  });

  it("retries reads only for network, server and provider errors", () => {
    expect(isRetryable(new ApiError({ status: 500, code: "internal_error", message: "x" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 503, code: "provider_unavailable", message: "x" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 0, code: "network_error", message: "x" }))).toBe(true);
    expect(isRetryable(new ApiError({ status: 404, code: "not_found", message: "x" }))).toBe(false);
    expect(isRetryable(new ApiError({ status: 422, code: "validation_error", message: "x" }))).toBe(false);
    expect(isRetryable(new Error("plain"))).toBe(false);
  });
});
