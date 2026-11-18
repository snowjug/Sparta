import { describe, expect, it, vi } from "vitest";
import { ApiClient, filenameFromDisposition, newIdempotencyKey, parseRetryAfter, sanitizeFilename } from "./client";
import { ApiError, describeError, fieldErrors, isApiError } from "./errors";
import { createEndpoints } from "./endpoints";
import { apiError, createFakeApi, json } from "@/test/fake-fetch";

function client(api = createFakeApi(), extra: Partial<ConstructorParameters<typeof ApiClient>[0]> = {}) {
  return new ApiClient({ baseUrl: "http://api.test/", fetchImpl: api.fetch, createRequestId: () => "req-1", ...extra });
}

describe("ApiClient", () => {
  it("builds versioned URLs, drops empty query values and trims the base URL", async () => {
    const api = createFakeApi({ "GET /api/v1/calls": () => ({ items: [], next_cursor: null }) });
    await client(api).get("/calls", { query: { q: "bank", limit: 5, cursor: "", attention: undefined, flag: false } });
    const [call] = api.calls;
    expect(call?.path).toBe("/api/v1/calls");
    expect(call?.query.get("q")).toBe("bank");
    expect(call?.query.get("limit")).toBe("5");
    expect(call?.query.get("flag")).toBe("false");
    expect(call?.query.has("cursor")).toBe(false);
    expect(call?.query.has("attention")).toBe(false);
  });

  it("sends JSON bodies, request id, idempotency key and auth headers", async () => {
    const api = createFakeApi({ "POST /api/v1/calls/c1/block": () => json({ id: "b1" }) });
    const c = client(api, { getAuthHeaders: async () => ({ "X-Sparta-Dev-User": "alice" }) });
    await c.post("/calls/c1/block", { reason: "spam" }, { idempotencyKey: "key-123" });
    const [call] = api.calls;
    expect(call?.headers.get("Content-Type")).toBe("application/json");
    expect(call?.headers.get("Idempotency-Key")).toBe("key-123");
    expect(call?.headers.get("X-Request-ID")).toBe("req-1");
    expect(call?.headers.get("X-Sparta-Dev-User")).toBe("alice");
    expect(call?.body).toEqual({ reason: "spam" });
  });

  it("does not force a content type on multipart bodies", async () => {
    const api = createFakeApi({ "POST /api/v1/calls/c1/audio": () => ({}) });
    const endpoints = createEndpoints(client(api));
    await endpoints.calls.sendAudio("c1", new Blob(["RIFF"], { type: "audio/wav" }), "clip.wav", { transcript_hint: "hello" });
    const [call] = api.calls;
    expect(call?.headers.has("Content-Type")).toBe(false);
    expect(call?.body).toMatchObject({ file: "file:clip.wav:4", transcript_hint: "hello" });
  });

  it("returns undefined for 204 and empty bodies", async () => {
    const api = createFakeApi({ "DELETE /api/v1/calls/c1": () => undefined });
    await expect(client(api).delete("/calls/c1")).resolves.toBeUndefined();
  });

  it("maps the API error envelope to ApiError with trace id and field details", async () => {
    const api = createFakeApi({
      "PUT /api/v1/preferences": () =>
        apiError(422, "validation_error", "Request validation failed", { trace_id: "t-42", details: [{ field: "takeover_number", message: "Invalid phone number" }] }),
    });
    const error = await client(api).put("/preferences", {}).catch((e: unknown) => e);
    expect(isApiError(error)).toBe(true);
    const apiErr = error as ApiError;
    expect(apiErr.status).toBe(422);
    expect(apiErr.code).toBe("validation_error");
    expect(apiErr.kind).toBe("validation");
    expect(apiErr.traceId).toBe("t-42");
    expect(apiErr.details).toEqual([{ field: "takeover_number", message: "Invalid phone number" }]);
    expect(fieldErrors(apiErr)).toEqual({ takeover_number: "Invalid phone number" });
  });

  it("shows a validation error that has no field details next to the form's own field, when told which one", async () => {
    const api = createFakeApi({
      "POST /api/v1/blocked-callers": () => apiError(422, "validation_error", "Enter a valid phone number, for example +91 98765 43210."),
    });
    const error = await client(api).post("/blocked-callers", { number: "abc" }).catch((e: unknown) => e);
    expect(fieldErrors(error)).toEqual({});
    expect(fieldErrors(error, "number")).toEqual({ number: "Enter a valid phone number, for example +91 98765 43210." });
    // Field details always win, and other kinds of errors are never turned into field errors.
    expect(fieldErrors(new ApiError({ status: 422, code: "validation_error", message: "m", details: [{ field: "body.reason", message: "Too long" }] }), "number")).toEqual({ reason: "Too long" });
    expect(fieldErrors(new ApiError({ status: 409, code: "conflict", message: "Nope" }), "number")).toEqual({});
  });

  it("reads Retry-After on 429 (seconds and HTTP date)", async () => {
    const api = createFakeApi({ "GET /api/v1/home": () => apiError(429, "rate_limited", "Slow down", { headers: { "Retry-After": "7" } }) });
    const error = (await client(api).get("/home").catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("rate_limited");
    expect(error.retryAfterS).toBe(7);
    expect(describeError(error).message).toMatch(/7 seconds/);
    expect(parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT", Date.parse("Wed, 21 Oct 2026 07:27:30 GMT"))).toBe(30);
    expect(parseRetryAfter(null)).toBeNull();
  });

  it("surfaces unsupported_by_provider with the server's own message", async () => {
    const api = createFakeApi({ "POST /api/v1/calls/c1/takeover": () => apiError(409, "unsupported_by_provider", "This provider cannot bridge the call to you.") });
    const error = (await client(api).post("/calls/c1/takeover", {}).catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("unsupported_by_provider");
    expect(describeError(error).message).toBe("This provider cannot bridge the call to you.");
  });

  it("explains stt_unavailable in plain words", () => {
    const error = new ApiError({ status: 422, code: "stt_unavailable", message: "STT is the simulator" });
    const described = describeError(error);
    expect(described.kind).toBe("stt_unavailable");
    expect(described.message).toMatch(/cannot transcribe audio/i);
    expect(described.message).toMatch(/transcript hint/i);
  });

  it("turns a network failure into a clear ApiError (status 0)", async () => {
    const failing = (async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const error = (await new ApiClient({ baseUrl: "http://api.test", fetchImpl: failing }).get("/home").catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("network");
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/Cannot reach the Sparta API at http:\/\/api\.test/);
    expect(describeError(error).retryable).toBe(true);
  });

  it("copes with non-JSON error bodies and FastAPI-style detail", async () => {
    const api = createFakeApi({
      "GET /api/v1/a": () => new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }),
      "GET /api/v1/b": () => json({ detail: [{ loc: ["body", "text"], msg: "Field required" }] }, { status: 422 }),
    });
    const a = (await client(api).get("/a").catch((e: unknown) => e)) as ApiError;
    expect(a.code).toBe("http_502");
    expect(a.kind).toBe("server");
    const b = (await client(api).get("/b").catch((e: unknown) => e)) as ApiError;
    expect(b.details).toEqual([{ field: "body.text", message: "Field required" }]);
  });

  it("notifies on 401 and reports aborts distinctly", async () => {
    const onUnauthorized = vi.fn();
    const api = createFakeApi({ "GET /api/v1/home": () => apiError(401, "unauthorized", "Sign in") });
    await client(api, { onUnauthorized }).get("/home").catch(() => undefined);
    expect(onUnauthorized).toHaveBeenCalledOnce();

    const abortFetch = (async () => {
      throw new DOMException("aborted", "AbortError");
    }) as unknown as typeof fetch;
    const error = (await new ApiClient({ baseUrl: "http://x", fetchImpl: abortFetch }).get("/home").catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("aborted");
  });

  it("downloads blobs and reads the filename from Content-Disposition", async () => {
    const api = createFakeApi({
      "GET /api/v1/calls/c1/report": () => new Response("{}", { headers: { "Content-Disposition": 'attachment; filename="sparta-report-c1.json"' } }),
    });
    const { blob, filename } = await client(api).download("GET", "/calls/c1/report");
    expect(filename).toBe("sparta-report-c1.json");
    expect(await blob.text()).toBe("{}");
  });

  it("sanitises filenames and parses RFC 5987 names", () => {
    expect(sanitizeFilename("../../etc/passwd")).toBe("_.._etc_passwd");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.json")).toBe("résumé.json");
    expect(filenameFromDisposition(null)).toBeNull();
  });

  it("generates idempotency keys the API accepts (1-64 chars, safe charset)", () => {
    const key = newIdempotencyKey();
    expect(key).toMatch(/^[A-Za-z0-9_\-:.]{1,64}$/);
    expect(newIdempotencyKey()).not.toBe(key);
  });
});
