"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { isOidcAuth } from "@/lib/auth/oidc";
import { useAuth } from "@/lib/auth/provider";
import { Button } from "@/components/ui/button";
import { LoadingBlock } from "@/components/ui/feedback";
import { Card } from "@/components/ui/layout";

/** OIDC redirect target: exchanges the authorization code (PKCE), then continues to the page the owner came from. */
export function CallbackScreen() {
  const auth = useAuth();
  const router = useRouter();
  const [problem, setProblem] = useState<string | null>(null);
  // The code can be exchanged only once; React strict mode runs effects twice in development.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!isOidcAuth(auth)) {
      router.replace("/");
      return;
    }
    auth
      .completeSignIn()
      .then((destination) => router.replace(destination))
      .catch((cause: unknown) => setProblem(cause instanceof Error && cause.message ? cause.message : "Sign-in could not be completed."));
  }, [auth, router]);

  if (problem) {
    return (
      <div className="mx-auto w-full max-w-md py-10" data-testid="callback-problem">
        <Card className="space-y-4" role="alert">
          <h1 className="text-xl font-semibold tracking-tight text-fg">Sign-in did not complete</h1>
          <p className="text-base text-fg">{problem}</p>
          <Button variant="primary" onClick={() => router.replace("/")}>
            Back to sign in
          </Button>
        </Card>
      </div>
    );
  }
  return <LoadingBlock label="Finishing sign-in" lines={3} />;
}
