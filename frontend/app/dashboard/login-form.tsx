"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { getSiteUrl } from "@/lib/env";

type Mode = "signin" | "signup";

export default function LoginForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setMessage(null);

    const supabase = createClient();

    if (mode === "signin") {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password
      });
      if (signInError) {
        setError(signInError.message);
        setPending(false);
        return;
      }
      router.refresh();
      return;
    }

    const { data, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${getSiteUrl()}/auth/callback`
      }
    });
    if (signUpError) {
      setError(signUpError.message);
      setPending(false);
      return;
    }

    // If email confirmation is off, a session is created immediately.
    if (data.session) {
      router.refresh();
      return;
    }

    setMessage("Check your email to confirm your account, then sign in.");
    setPending(false);
  }

  return (
    <div className="mx-auto max-w-md px-6 py-16">
      <div className="rounded-xl border border-surface-border bg-white p-8">
        <h1 className="text-2xl font-bold text-ink">
          {mode === "signin" ? "Sign in" : "Create your account"}
        </h1>
        <p className="mt-1 text-sm text-ink-soft">
          {mode === "signin"
            ? "Access your API keys, usage, and billing."
            : "Start on the free tier - 50 lookups per month."}
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-ink">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-surface-border px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-ink">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-surface-border px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
            />
          </div>

          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          {message ? <p className="text-sm text-emerald-600">{message}</p> : null}

          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-md bg-brand px-4 py-2 font-medium text-white hover:bg-brand-dark disabled:opacity-60"
          >
            {pending ? "Please wait..." : mode === "signin" ? "Sign in" : "Sign up"}
          </button>
        </form>

        <div className="mt-4 text-center text-sm text-ink-soft">
          {mode === "signin" ? (
            <button
              type="button"
              onClick={() => {
                setMode("signup");
                setError(null);
                setMessage(null);
              }}
              className="text-brand hover:text-brand-dark"
            >
              Need an account? Sign up
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                setMode("signin");
                setError(null);
                setMessage(null);
              }}
              className="text-brand hover:text-brand-dark"
            >
              Already have an account? Sign in
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
