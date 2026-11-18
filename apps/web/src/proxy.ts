import { NextResponse, type NextRequest } from "next/server";
import { getApiBaseUrl } from "@/lib/api/config";
import { buildContentSecurityPolicy, createNonce } from "@/lib/csp";

/** Sets a per-request, nonce-based Content-Security-Policy. Pages are rendered per request (see the root layout) so Next.js can stamp the nonce on its scripts. */
export function proxy(request: NextRequest) {
  const nonce = createNonce();
  const policy = buildContentSecurityPolicy({
    nonce,
    dev: process.env.NODE_ENV === "development",
    apiBaseUrl: getApiBaseUrl(),
    extraConnectOrigins: [process.env.NEXT_PUBLIC_OIDC_AUTHORITY ?? ""],
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Documents only: static assets and prefetches do not render HTML.
      source: "/((?!_next/static|_next/image|favicon.svg|theme-init.js).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
