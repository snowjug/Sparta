"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { isOidcAuth } from "@/lib/auth/oidc";
import { useAuth, useAuthSession } from "@/lib/auth/provider";
import { Button } from "@/components/ui/button";
import { LoadingBlock } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";
import { Card } from "@/components/ui/layout";
import { Brand } from "@/components/brand/logo";

function SignInCard({ onSignIn }: { onSignIn: () => Promise<void> }) {
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setProblem(null);
    try {
      await onSignIn();
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : "Sign-in could not be started.");
      setPending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-md py-10" data-testid="sign-in">
      <Card className="space-y-5 text-center">
        <div className="flex justify-center">
          <Brand />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Sign in to Sparta</h1>
        <p className="text-base text-muted">Sparta uses your organisation&apos;s single sign-on. You are sent to your identity provider and brought back here.</p>
        <Button variant="primary" size="lg" fullWidth icon="key" loading={pending} onClick={() => void start()} data-testid="sign-in-button">
          Sign in
        </Button>
        {problem ? (
          <p role="alert" className="rounded-2xl border border-danger/40 bg-danger-bg px-4 py-3 text-sm text-fg">
            {problem}
          </p>
        ) : null}
      </Card>
    </div>
  );
}

function NotConfigured() {
  return (
    <div className="mx-auto w-full max-w-lg py-10" data-testid="oidc-not-configured">
      <Card className="space-y-3" role="alert">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-fg">
          <Icon name="alert" size={22} className="text-warning" />
          Sign-in is not configured
        </h1>
        <p className="text-base text-fg">
          This build uses OIDC sign-in (<code className="font-mono text-sm">NEXT_PUBLIC_AUTH_MODE=oidc</code>) but no identity provider was set. Build it with{" "}
          <code className="font-mono text-sm">NEXT_PUBLIC_OIDC_AUTHORITY</code> and <code className="font-mono text-sm">NEXT_PUBLIC_OIDC_CLIENT_ID</code>.
        </p>
      </Card>
    </div>
  );
}

/**
 * With OIDC the app is shown only to a signed-in owner. Development authentication has nothing to sign in to, so this renders
 * its children unchanged. The OIDC redirect target (/auth/callback) always renders: it is where the sign-in is completed.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const session = useAuthSession();
  const pathname = usePathname();
  if (!isOidcAuth(auth) || pathname.startsWith("/auth/callback")) return <>{children}</>;
  if (!auth.configured) return <NotConfigured />;
  if (session.status === "loading") return <LoadingBlock label="Checking your sign-in" lines={3} />;
  if (session.status === "signed_out") return <SignInCard onSignIn={() => auth.signIn(pathname)} />;
  return <>{children}</>;
}

/** Who is signed in, with a sign-out button. Nothing is rendered for development authentication. */
export function AccountChip() {
  const auth = useAuth();
  const session = useAuthSession();
  if (!isOidcAuth(auth) || session.status !== "signed_in") return null;
  return (
    <div className="flex items-center gap-2" data-testid="account-chip">
      {session.name ? <span className="hidden max-w-40 truncate text-sm text-muted sm:inline">{session.name}</span> : null}
      <Button variant="secondary" size="sm" onClick={() => void auth.signOut()}>
        Sign out
      </Button>
    </div>
  );
}
