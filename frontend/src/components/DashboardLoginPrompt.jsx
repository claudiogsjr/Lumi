import { AlertCircle, BarChart3, KeyRound, LogOut } from "lucide-react";
import { useState } from "react";
import { postJson } from "../api";
import { GlassCard } from "../components/LumiSurface";

export function DashboardLoginPrompt({ user, error, onAuthenticated, onLogout }) {
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    if (!token.trim()) {
      setLocalError("Informe o token de acesso.");
      return;
    }
    try {
      setLoading(true);
      setLocalError("");
      const data = await postJson("/api/auth/token/login", { token });
      setToken("");
      onAuthenticated(data.user || null);
    } catch (err) {
      setLocalError(err.message || "Falha ao autenticar.");
    } finally {
      setLoading(false);
    }
  }

  if (user) {
    return (
      <GlassCard className="p-5 lg:p-6">
        <div className="flex items-center justify-between gap-4 flex-col md:flex-row">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[hsl(201,96%,72%)]">
              <BarChart3 className="h-5 w-5" />
              <span className="text-sm font-semibold uppercase tracking-[0.12em]">Dashboard autenticado</span>
            </div>
            <p className="text-sm text-white/65">Acesso administrativo liberado.</p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            className="inline-flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/85 hover:bg-white/[0.08]"
          >
            <LogOut className="h-4 w-4" />
            Sair
          </button>
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-8 text-center max-w-xl mx-auto">
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-[hsl(201,96%,52%,0.12)]">
        <KeyRound className="h-8 w-8 text-[hsl(201,96%,72%)]" />
      </div>
      <div className="mt-6 space-y-3">
        <h2 className="text-xl font-semibold text-white">Acesso restrito</h2>
        <p className="text-sm leading-6 text-white/65">
          O dashboard administrativo usa autenticação por token manual.
        </p>
      </div>
      {error || localError ? (
        <div className="mt-6 flex items-start gap-3 rounded-2xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-100 text-left">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>{error || localError}</div>
        </div>
      ) : null}
      <form onSubmit={handleSubmit} className="mt-8 space-y-4 text-left">
        <label className="block text-sm text-white/70">
          Token do dashboard
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="Informe o token"
            className="mt-2 w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-3 text-sm text-white placeholder:text-white/30 outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-xl bg-[hsl(201,96%,45%)] px-4 py-3 text-sm font-medium text-white shadow-[0_4px_20px_hsl(201,96%,40%,0.3)] hover:brightness-110 disabled:opacity-60"
        >
          {loading ? "Validando..." : "Entrar no dashboard"}
        </button>
      </form>
    </GlassCard>
  );
}
