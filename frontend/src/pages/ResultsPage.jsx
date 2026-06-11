import { Activity, BarChart3, Gauge, MessageSquareText, Route, Timer } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getJson, postJson } from "../api";
import { DashboardLoginPrompt } from "../components/DashboardLoginPrompt";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";

function formatMetric(value, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${value}${suffix}`;
}

function scoreColor(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "text-white";
  if (numeric >= 4.5) return "text-emerald-300";
  if (numeric >= 4.0) return "text-cyan-300";
  if (numeric >= 3.0) return "text-amber-300";
  return "text-rose-300";
}

function getTopBoxPct(items = []) {
  const total = items.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  if (!total) return null;
  const positive = items
    .filter((item) => Number(item.score) >= 4)
    .reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  return Number(((positive / total) * 100).toFixed(1));
}

function getBottomBoxPct(items = []) {
  const total = items.reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  if (!total) return null;
  const negative = items
    .filter((item) => Number(item.score) <= 2)
    .reduce((sum, item) => sum + (Number(item.count) || 0), 0);
  return Number(((negative / total) * 100).toFixed(1));
}

function KpiCard({ title, value, subtitle, icon: Icon, tone = "default" }) {
  const toneClasses = {
    default: "from-slate-900/80 to-slate-900/40 border-white/10",
    blue: "from-sky-950/80 to-sky-900/40 border-sky-400/20",
    green: "from-emerald-950/80 to-emerald-900/40 border-emerald-400/20",
    amber: "from-amber-950/80 to-amber-900/40 border-amber-400/20",
  };

  return (
    <GlassCard className={`p-5 lg:p-6 bg-gradient-to-br ${toneClasses[tone] || toneClasses.default}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/45">{title}</p>
          <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{value}</div>
          {subtitle ? <p className="mt-2 text-sm text-white/60">{subtitle}</p> : null}
        </div>
        {Icon ? (
          <div className="rounded-2xl border border-white/10 bg-white/5 p-3 text-[hsl(201,96%,72%)]">
            <Icon className="h-5 w-5" />
          </div>
        ) : null}
      </div>
    </GlassCard>
  );
}

function HorizontalBarCard({ title, items, emptyLabel = "Sem dados suficientes." }) {
  const max = Math.max(...((items || []).map((item) => Number(item.count) || 0)), 0);

  return (
    <GlassCard className="p-5 lg:p-6">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <span className="text-[11px] uppercase tracking-[0.12em] text-white/35">Distribuição</span>
      </div>
      <div className="mt-5 space-y-3">
        {!items || items.length === 0 ? (
          <p className="text-sm text-white/50">{emptyLabel}</p>
        ) : (
          items.map((item) => (
            <div key={`${title}-${item.label || item.score || item.route}`} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-sm text-white/75">
                <span>{item.label || `Nota ${item.score}` || item.route}</span>
                <span className="font-mono-data text-white">
                  {item.count}
                  {item.pct != null ? ` (${item.pct}%)` : ""}
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-white/[0.07]">
                <div
                  className="h-full rounded-full bg-[linear-gradient(90deg,hsl(201,96%,45%),hsl(201,96%,68%))]"
                  style={{ width: `${max ? (Number(item.count || 0) / max) * 100 : 0}%` }}
                />
              </div>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}

function DistributionCard({ title, average, items }) {
  const topBox = getTopBoxPct(items);
  const bottomBox = getBottomBoxPct(items);

  return (
    <GlassCard className="p-5 lg:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="mt-1 text-xs text-white/45">Escala Likert de 1 a 5</p>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-semibold ${scoreColor(average)}`}>{formatMetric(average)}</div>
          <div className="text-xs text-white/45">Média</div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.12em] text-white/40">Favoráveis</div>
          <div className="mt-2 text-xl font-semibold text-emerald-300">{formatMetric(topBox, "%")}</div>
          <div className="text-xs text-white/45">Notas 4 e 5</div>
        </div>
        <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.12em] text-white/40">Críticas</div>
          <div className="mt-2 text-xl font-semibold text-rose-300">{formatMetric(bottomBox, "%")}</div>
          <div className="text-xs text-white/45">Notas 1 e 2</div>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        {(items || []).map((item) => (
          <div key={`${title}-${item.score}`} className="space-y-1.5">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>Nota {item.score}</span>
              <span className="font-mono-data text-white">
                {item.count} ({item.pct}%)
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-white/[0.08]">
              <div
                className="h-full rounded-full bg-[linear-gradient(90deg,hsl(201,96%,45%),hsl(201,96%,68%))]"
                style={{ width: `${item.pct || 0}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function LatencyHistogram({ bins }) {
  const maxLatencyCount = Math.max(...(bins || []).map((bin) => Number(bin.count) || 0), 1);

  return (
    <GlassCard className="p-5 lg:p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-white">Histograma de latência</h2>
        <span className="text-[11px] uppercase tracking-[0.12em] text-white/35">Tempo de resposta</span>
      </div>
      <div className="mt-6 grid min-h-[260px] grid-cols-2 items-end gap-3 md:grid-cols-4 xl:grid-cols-8">
        {!bins || bins.length === 0 ? (
          <p className="col-span-full text-sm text-white/50">Não há dados suficientes de latência.</p>
        ) : (
          bins.map((item) => (
            <div key={item.label} className="space-y-2">
              <div className="flex h-40 items-end rounded-2xl border border-white/8 bg-white/[0.04] p-2">
                <div
                  className="w-full rounded-xl bg-[linear-gradient(180deg,hsl(201,96%,68%),hsl(201,96%,45%))]"
                  style={{ height: `${((Number(item.count) || 0) / maxLatencyCount) * 100}%` }}
                />
              </div>
              <div className="text-center text-xs text-white/50">
                <div className="font-mono-data text-white">{item.count}</div>
                <div>{item.label} ms</div>
              </div>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}

export default function ResultsPage() {
  const [performanceData, setPerformanceData] = useState(null);
  const [usabilityData, setUsabilityData] = useState(null);
  const [status, setStatus] = useState("Carregando...");
  const [dashboardUser, setDashboardUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

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
          setAuthError(error.message || "Falha ao verificar acesso ao dashboard.");
        }
        setDashboardUser(null);
      }
    } catch (error) {
      setAuthError(error.message || "Falha ao carregar autenticação do dashboard.");
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const loadDashboardData = useCallback(async () => {
    setStatus("Carregando...");
    try {
      const [usability, performance] = await Promise.all([
        getJson("/api/usability/results/aggregate"),
        getJson("/results-data"),
      ]);
      setUsabilityData(usability);
      setPerformanceData(performance);
      setStatus("OK");
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    }
  }, []);

  useEffect(() => {
    loadDashboardAuth();
  }, [loadDashboardAuth]);

  useEffect(() => {
    if (!dashboardUser) return;
    loadDashboardData();
  }, [dashboardUser, loadDashboardData]);

  const handleLogout = useCallback(async () => {
    await postJson("/api/auth/logout", {});
    setDashboardUser(null);
    setUsabilityData(null);
    setPerformanceData(null);
    setStatus("Acesso restrito.");
  }, []);

  const averageScores = usabilityData?.averages || {};
  const satisfactionAverage = averageScores.satisfaction_score;
  const overallAverage = useMemo(() => {
    const values = [
      averageScores.clarity_score,
      averageScores.usefulness_score,
      averageScores.adequacy_score,
      averageScores.ease_of_use_score,
      averageScores.satisfaction_score,
    ].filter((value) => value != null && !Number.isNaN(Number(value))).map(Number);
    if (!values.length) return null;
    return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2));
  }, [averageScores]);

  const topRoute = useMemo(() => {
    const routes = usabilityData?.routes || [];
    if (!routes.length) return null;
    return [...routes].sort((a, b) => Number(b.count || 0) - Number(a.count || 0))[0];
  }, [usabilityData]);

  const routeTotal = useMemo(
    () => (usabilityData?.routes || []).reduce((sum, item) => sum + (Number(item.count) || 0), 0),
    [usabilityData],
  );

  const routeItems = useMemo(() => {
    const routes = usabilityData?.routes || [];
    if (!routeTotal) return routes;
    return routes.map((item) => ({
      ...item,
      label: item.route,
      pct: Number((((Number(item.count) || 0) / routeTotal) * 100).toFixed(1)),
    }));
  }, [usabilityData, routeTotal]);

  const commentsCount = (usabilityData?.comments || []).length;
  const latencyMetrics = performanceData?.metrics || {};
  const latencySpread =
    latencyMetrics.latency_p95_ms != null && latencyMetrics.latency_p50_ms != null
      ? Number((Number(latencyMetrics.latency_p95_ms) - Number(latencyMetrics.latency_p50_ms)).toFixed(2))
      : null;

  return (
    <LumiPage>
      <PageHeader
        title="Dashboard"
        description="Painel executivo com métricas de usabilidade, engajamento e desempenho operacional da LUMI."
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
            <KpiCard
              title="Média geral"
              value={formatMetric(overallAverage)}
              subtitle="Síntese consolidada das cinco dimensões avaliadas"
              icon={Gauge}
              tone="blue"
            />
            <KpiCard
              title="Satisfação"
              value={formatMetric(satisfactionAverage)}
              subtitle="Percepção geral dos usuários sobre a experiência"
              icon={MessageSquareText}
              tone="green"
            />
            <KpiCard
              title="Sessões concluídas"
              value={formatMetric(usabilityData?.sessions?.finished)}
              subtitle={`Taxa de conclusão ${formatMetric(usabilityData?.sessions?.completion_rate, "%")}`}
              icon={Activity}
              tone="amber"
            />
            <KpiCard
              title="Latência média"
              value={formatMetric(latencyMetrics.latency_mean_ms, " ms")}
              subtitle={`p95 ${formatMetric(latencyMetrics.latency_p95_ms, " ms")}`}
              icon={Timer}
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
            <GlassCard className="p-5 lg:p-6">
              <div className="flex items-center justify-between gap-4 flex-col md:flex-row">
                <div>
                  <h2 className="text-base font-semibold text-white">Resumo executivo</h2>
                  <p className="mt-1 text-sm text-white/60">
                    Indicadores centrais de qualidade percebida, adesão ao fluxo e cobertura das interações.
                  </p>
                </div>
                <div className="rounded-full border border-[hsl(201,96%,52%,0.25)] bg-[hsl(201,96%,52%,0.12)] px-3 py-1 text-xs font-medium text-[hsl(201,96%,72%)]">
                  {usabilityData?.n ?? 0} avaliações registradas
                </div>
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricPill label="Sessões iniciadas" value={formatMetric(usabilityData?.sessions?.started)} />
                <MetricPill label="Média de interações" value={formatMetric(usabilityData?.sessions?.avg_chat_turns)} />
                <MetricPill label="Comentários recentes" value={formatMetric(commentsCount)} />
                <MetricPill label="Rota líder" value={topRoute ? `${topRoute.route} (${topRoute.count})` : "-"} />
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
                <MetricPill label="Clareza" value={formatMetric(averageScores.clarity_score)} />
                <MetricPill label="Utilidade" value={formatMetric(averageScores.usefulness_score)} />
                <MetricPill label="Adequação" value={formatMetric(averageScores.adequacy_score)} />
                <MetricPill label="Facilidade" value={formatMetric(averageScores.ease_of_use_score)} />
                <MetricPill label="Satisfação" value={formatMetric(averageScores.satisfaction_score)} />
              </div>
            </GlassCard>

            <GlassCard className="p-5 lg:p-6">
              <div className="flex items-center gap-2 text-[hsl(201,96%,72%)]">
                <BarChart3 className="h-4 w-4" />
                <h2 className="text-base font-semibold text-white">Painel de performance</h2>
              </div>
              <div className="mt-5 space-y-4">
                <MetricPill label="p50" value={formatMetric(latencyMetrics.latency_p50_ms, " ms")} />
                <MetricPill label="p95" value={formatMetric(latencyMetrics.latency_p95_ms, " ms")} />
                <MetricPill label="Amplitude p95 - p50" value={formatMetric(latencySpread, " ms")} />
                <MetricPill label="Eventos de rota" value={formatMetric(routeTotal)} />
              </div>
            </GlassCard>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <DistributionCard title="Clareza" average={averageScores.clarity_score} items={usabilityData?.distributions?.clarity_score} />
            <DistributionCard title="Utilidade" average={averageScores.usefulness_score} items={usabilityData?.distributions?.usefulness_score} />
            <DistributionCard title="Adequação" average={averageScores.adequacy_score} items={usabilityData?.distributions?.adequacy_score} />
            <DistributionCard title="Facilidade" average={averageScores.ease_of_use_score} items={usabilityData?.distributions?.ease_of_use_score} />
            <DistributionCard title="Satisfação" average={averageScores.satisfaction_score} items={usabilityData?.distributions?.satisfaction_score} />
            <HorizontalBarCard title="Distribuição por rota" items={routeItems} emptyLabel="Nenhuma rota agregada." />
          </div>

          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <GlassCard className="p-5 lg:p-6">
              <div className="flex items-center gap-2 text-[hsl(201,96%,72%)]">
                <Route className="h-4 w-4" />
                <h2 className="text-base font-semibold text-white">Funil de participação</h2>
              </div>
              <div className="mt-6 space-y-5">
                {[
                  { label: "Sessões iniciadas", value: usabilityData?.sessions?.started || 0 },
                  { label: "Sessões concluídas", value: usabilityData?.sessions?.finished || 0 },
                  { label: "Comentários enviados", value: commentsCount },
                ].map((item, index, arr) => {
                  const base = Number(arr[0].value) || 0;
                  const pct = base ? Number((((Number(item.value) || 0) / base) * 100).toFixed(1)) : 0;
                  return (
                    <div key={item.label} className="space-y-1.5">
                      <div className="flex items-center justify-between text-sm text-white/75">
                        <span>{item.label}</span>
                        <span className="font-mono-data text-white">{item.value}</span>
                      </div>
                      <div className="h-3 overflow-hidden rounded-full bg-white/[0.06]">
                        <div
                          className="h-full rounded-full bg-[linear-gradient(90deg,hsl(201,96%,45%),hsl(201,96%,68%))]"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="text-xs text-white/45">{pct}% da base inicial</div>
                    </div>
                  );
                })}
              </div>
            </GlassCard>

            <LatencyHistogram bins={performanceData?.latency?.bins || []} />
          </div>

          <GlassCard className="p-5 lg:p-6">
            <div className="flex items-center justify-between gap-4 flex-col md:flex-row">
              <div>
                <h2 className="text-base font-semibold text-white">Comentários recentes</h2>
                <p className="mt-1 text-sm text-white/60">
                  Últimos comentários livres enviados no fluxo de avaliação.
                </p>
              </div>
              <MetricPill label="Total exibido" value={formatMetric(commentsCount)} />
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {(usabilityData?.comments || []).length === 0 ? (
                <p className="text-sm text-white/50">Nenhum comentário registrado.</p>
              ) : (
                usabilityData.comments.map((item, index) => (
                  <div
                    key={`${item.session_id}-${index}`}
                    className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-4"
                  >
                    <div className="flex items-center gap-3 text-xs text-white/45">
                      <span>Sessão {String(item.session_id || "").slice(0, 8)}</span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-white/85">{item.comment}</p>
                  </div>
                ))
              )}
            </div>
          </GlassCard>
        </>
      )}
    </LumiPage>
  );
}
