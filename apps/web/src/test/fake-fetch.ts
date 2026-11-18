/** A tiny typed fake of `fetch` for tests: route table in, recorded requests out. No network, no extra dependency. */

export interface RecordedRequest {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Headers;
  body: unknown;
  rawBody: BodyInit | null | undefined;
}

export type Handler = (request: RecordedRequest, params: Record<string, string>) => Response | Promise<Response> | unknown;

export function json(body: unknown, init: ResponseInit & { status?: number } = {}): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return new Response(init.status === 204 ? null : JSON.stringify(body), { ...init, headers });
}

export function apiError(status: number, code: string, message: string, extra: { details?: Array<{ field: string; message: string }>; headers?: Record<string, string>; trace_id?: string } = {}): Response {
  return json({ error: { code, message, trace_id: extra.trace_id ?? "trace-test-1", details: extra.details ?? null } }, { status, headers: extra.headers });
}

function compile(pattern: string): { method: string; regex: RegExp; names: string[] } {
  const [method, path] = pattern.split(" ") as [string, string];
  const names: string[] = [];
  const source = path
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\\\{(\w+)\\\}/g, (_m, name: string) => {
      names.push(name);
      return "([^/]+)";
    });
  return { method, regex: new RegExp(`^${source}$`), names };
}

export interface FakeApi {
  fetch: typeof fetch;
  calls: RecordedRequest[];
  /** Replace or add a route at runtime. */
  on(pattern: string, handler: Handler): void;
  callsTo(pattern: string): RecordedRequest[];
}

/** Routes are keyed `"GET /api/v1/home"`; `{id}` captures a path segment. Unknown routes answer 404 with the API envelope. */
export function createFakeApi(routes: Record<string, Handler> = {}): FakeApi {
  const table = new Map<string, { compiled: ReturnType<typeof compile>; handler: Handler }>();
  const add = (pattern: string, handler: Handler) => table.set(pattern, { compiled: compile(pattern), handler });
  for (const [pattern, handler] of Object.entries(routes)) add(pattern, handler);
  const calls: RecordedRequest[] = [];

  const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = null;
    const raw = init?.body;
    if (typeof raw === "string") {
      try {
        body = JSON.parse(raw);
      } catch {
        body = raw;
      }
    } else if (raw instanceof FormData) {
      body = Object.fromEntries([...raw.entries()].map(([k, v]) => [k, v instanceof File ? `file:${v.name}:${v.size}` : v]));
    }
    const request: RecordedRequest = { method, path: url.pathname, query: url.searchParams, headers: new Headers(init?.headers), body, rawBody: raw };
    calls.push(request);
    for (const { compiled, handler } of table.values()) {
      if (compiled.method !== method) continue;
      const match = compiled.regex.exec(url.pathname);
      if (!match) continue;
      const params: Record<string, string> = {};
      compiled.names.forEach((name, i) => (params[name] = decodeURIComponent(match[i + 1]!)));
      const result = await handler(request, params);
      return result instanceof Response ? result : json(result ?? null, result === undefined ? { status: 204 } : {});
    }
    return apiError(404, "not_found", `No fake route for ${method} ${url.pathname}`);
  }) as typeof fetch;

  return {
    fetch: fakeFetch,
    calls,
    on: add,
    callsTo: (pattern) => {
      const { method, regex } = compile(pattern);
      return calls.filter((call) => call.method === method && regex.test(call.path));
    },
  };
}
