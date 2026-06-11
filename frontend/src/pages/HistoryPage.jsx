import { History, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getJson, postJson } from "../api";
import { DashboardLoginPrompt } from "../components/DashboardLoginPrompt";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";

function LogMetric({ label, value }) {
  return <MetricPill label={label} value={value != null && value !== "" ? String(value) : "-"} />;
}

function formatTs(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").replace("Z", "");
}

function truncate(value, size = 160) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.length > size ? `${text.slice(0, size)}...` : text;
}

export default function HistoryPage() {
  const [dashboardUser, setDashboardUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [status, setStatus] = useState("Carregando...");
  const [rows, setRows] = useState([]);
  const [filters, setFilters] = useState({ session_id: "", intent: "", limit: 50 });

  const loadDashboardAuth = useCallback(async () => {
    setAuthLoading(true);
    setAuthError("");
    try {
      await getJson("/api/auth/config");
      try {
        const me = await getJson("/api/auth/me");
        setDashboardUser(me.user || null);
      } catch (error) {
        if (!String(error.message || "").includes("Não autenticado") && !String(error.message || "").includes("Nao autenticado")) {
          setAuthError(error.message || "Falha ao verificar acesso ao histórico.");
        }
        setDashboardUser(null);
      }
    } catch (error) {
      setAuthError(error.message || "Falha ao carregar autenticação.");
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const loadLogs = useCallback(async () => {
    setStatus("Carregando...");
    try {
      const params = new URLSearchParams();
      if (filters.session_id) params.set("session_id", filters.session_id);
      if (filters.intent) params.set("intent", filters.intent);
      if (filters.limit) params.set("limit", String(filters.limit));
      const data = await getJson(`/logs-data?${params.toString()}`);
      const items = Array.isArray(data) ? data : [];
      setRows(items.slice().reverse());
      setStatus(`OK: ${items.length} registros carregados.`);
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    }
  }, [filters]);

  useEffect(() => {
    loadDashboardAuth();
  }, [loadDashboardAuth]);

  useEffect(() => {
    if (!dashboardUser) return;
    loadLogs();
  }, [dashboardUser, loadLogs]);

  const handleLogout = useCallback(async () => {
    await postJson("/api/auth/logout", {});
    setDashboardUser(null);
    setRows([]);
    setStatus("Acesso restrito.");
  }, []);

  const stats = useMemo(() => {
    const total = rows.length;
    const intents = rows.reduce((acc, item) => {
      const key = String(item.intent || "SEM_INTENT").toUpperCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    const avgLatency = total
      ? Number(
          (
            rows.reduce((sum, item) => sum + (Number(item.latency_ms) || 0), 0) /
            Math.max(total, 1)
          ).toFixed(1),
        )
      : null;
    const topIntent = Object.entries(intents).sort((a, b) => b[1] - a[1])[0]?.[0] || "-";
    return { total, avgLatency, topIntent, distinctSessions: new Set(rows.map((item) => item.session_id || item.user_id).filter(Boolean)).size };
  }, [rows]);

  return (
    <LumiPage>
      <PageHeader
        title="Histórico"
        description="Logs das interações dos usuários com a LUMI. Acesso restrito por token administrativo."
        badge={dashboardUser ? status : "Acesso restrito"}
      />

      {authLoading || !dashboardUser ? (
        <DashboardLoginPrompt user={dashboardUser} error={authError} onAuthenticated={setDashboardUser} onLogout={handleLogout} />
      ) : (
        <>
          <DashboardLoginPrompt
            user={dashboardUser}
            error={authError}
            onAuthenticated={setDashboardUser}
            onLogout={handleLogout}
          />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <LogMetric label="Registros" value={stats.total} />
            <LogMetric label="Usuários distintos" value={stats.distinctUsers} />
            <LogMetric label="Intent líder" value={stats.topIntent} />
            <LogMetric label="Latência média" value={stats.avgLatency != null ? `${stats.avgLatency} ms` : "-"} />
          </div>

          <GlassCard className="p-5 lg:p-6">
            <div className="flex items-center justify-between gap-4 flex-col lg:flex-row">
              <div>
                <div className="flex items-center gap-2 text-[hsl(201,96%,72%)]">
                  <History className="h-4 w-4" />
                  <span className="text-sm font-semibold uppercase tracking-[0.12em]">Filtros</span>
                </div>
                <p className="mt-2 text-sm text-white/60">Refine os logs por usuário, intent e volume exibido.</p>
              </div>
              <button
                type="button"
                onClick={loadLogs}
                className="inline-flex items-center gap-2 rounded-xl bg-[hsl(201,96%,45%)] px-4 py-2.5 text-sm font-medium text-white shadow-[0_4px_20px_hsl(201,96%,40%,0.3)] hover:brightness-110"
              >
                <RefreshCw className="h-4 w-4" />
                Atualizar
              </button>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <label className="text-sm space-y-2">
                <span className="text-white/65">Usuário</span>
                <input
                  value={filters.session_id}
                  onChange={(event) => setFilters((current) => ({ ...current, session_id: event.target.value }))}
                  placeholder="Ex.: 6f8d4d6c-..."
                  className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-white placeholder:text-white/30"
                />
              </label>
              <label className="text-sm space-y-2">
                <span className="text-white/65">Intent</span>
                <select
                  value={filters.intent}
                  onChange={(event) => setFilters((current) => ({ ...current, intent: event.target.value }))}
                  className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-white"
                >
                  <option value="">Todas</option>
                  <option value="PREVISAO">PREVISAO</option>
                  <option value="ESTACOES_RT">ESTACOES_RT</option>
                  <option value="GENERICO">GENERICO</option>
                </select>
              </label>
              <label className="text-sm space-y-2">
                <span className="text-white/65">Limite</span>
                <select
                  value={filters.limit}
                  onChange={(event) => setFilters((current) => ({ ...current, limit: Number(event.target.value) || 50 }))}
                  className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-white"
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                </select>
              </label>
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={() => setFilters({ user_id: "", intent: "", limit: 50 })}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/85 hover:bg-white/[0.08]"
                >
                  <Search className="h-4 w-4" />
                  Limpar filtros
                </button>
              </div>
            </div>
          </GlassCard>

          <GlassCard className="overflow-hidden p-0">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-white/[0.05] text-left text-white/70">
                  <tr>
                    <th className="px-4 py-3 font-medium">Usuário</th>
                    <th className="px-4 py-3 font-medium">Intent</th>
                    <th className="px-4 py-3 font-medium">Source</th>
                    <th className="px-4 py-3 font-medium">Latência</th>
                    <th className="px-4 py-3 font-medium">Mensagem</th>
                    <th className="px-4 py-3 font-medium">Resposta</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan="6" className="px-4 py-10 text-center text-white/50">
                        Nenhum log encontrado.
                      </td>
                    </tr>
                  ) : (
                    rows.map((item) => (
                      <tr key={item.id || `${item.ts}-${item.session_id || item.user_id}`} className="border-t border-white/[0.06] align-top text-white/85">
                        <td className="px-4 py-3 whitespace-nowrap">{item.session_id || item.user_id || "-"}</td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-xs">
                            {item.intent || "-"}
                          </span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-white/65">{item.decision_source || "-"}</td>
                        <td className="px-4 py-3 whitespace-nowrap font-mono-data">{item.latency_ms != null ? `${item.latency_ms} ms` : "-"}</td>
                        <td className="px-4 py-3 max-w-[320px] text-white/75">{truncate(item.message)}</td>
                        <td className="px-4 py-3 max-w-[420px] text-white/75">{truncate(item.response, 220)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </GlassCard>
        </>
      )}
    </LumiPage>
  );
}
