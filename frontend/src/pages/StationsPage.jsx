import { ArrowDownAZ, ArrowUpAZ, ArrowUpDown } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getJson } from "../api";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";

const SORTABLE_COLUMNS = [
  { key: "name", label: "Estação", type: "text" },
  { key: "rain_day", label: "Chuva", type: "number" },
  { key: "temp", label: "Temperatura", type: "number" },
  { key: "humi", label: "Umidade", type: "number" },
  { key: "wind", label: "Vento", type: "number" },
  { key: "gust", label: "Rajada", type: "number" },
  { key: "pres", label: "Pressão", type: "number" },
];

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function SortIcon({ active, direction, type }) {
  if (!active) return <ArrowUpDown className="h-3.5 w-3.5" />;
  if (type === "text") {
    return direction === "asc" ? (
      <ArrowDownAZ className="h-3.5 w-3.5" />
    ) : (
      <ArrowUpAZ className="h-3.5 w-3.5" />
    );
  }
  return (
    <ArrowUpDown
      className={`h-3.5 w-3.5 transition-transform ${direction === "desc" ? "rotate-180" : ""}`}
    />
  );
}

export default function StationsPage() {
  const [query, setQuery] = useState("");
  const [data, setData] = useState({ count: 0, items: [] });
  const [status, setStatus] = useState("Carregando estações...");
  const [sortBy, setSortBy] = useState("rain_day");
  const [sortDirection, setSortDirection] = useState("desc");

  const load = async (search = "") => {
    setStatus("Carregando...");
    try {
      const params = search ? `?q=${encodeURIComponent(search)}` : "";
      const result = await getJson(`/api/stations${params}`);
      setData(result);
      setStatus(`OK: ${result.count} estações carregadas.`);
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const rainSummary = useMemo(() => {
    const items = data.items || [];
    const total = items.reduce((acc, item) => acc + (Number(item.rain_day) || 0), 0);
    const raining = items.filter((item) => (Number(item.rain_day) || 0) > 0).length;
    return {
      total: formatNumber(total, 1),
      raining,
    };
  }, [data]);

  const sortedItems = useMemo(() => {
    const items = [...(data.items || [])];
    const column = SORTABLE_COLUMNS.find((item) => item.key === sortBy);
    items.sort((a, b) => {
      const av = a?.[sortBy];
      const bv = b?.[sortBy];
      let result = 0;
      if (column?.type === "number") {
        result = (Number(av) || 0) - (Number(bv) || 0);
      } else {
        result = String(av || "").localeCompare(String(bv || ""), "pt-BR", { sensitivity: "base" });
      }
      return sortDirection === "asc" ? result : -result;
    });
    return items;
  }, [data, sortBy, sortDirection]);

  const toggleSort = (key) => {
    if (sortBy === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortBy(key);
    const column = SORTABLE_COLUMNS.find((item) => item.key === key);
    setSortDirection(column?.type === "text" ? "asc" : "desc");
  };

  return (
    <LumiPage>
      <PageHeader
        title="Estações meteorológicas"
        description="Consulta operacional das estações Plugfield com chuva, vento, temperatura e umidade."
        badge={status}
      />

      <GlassCard className="p-5 lg:p-6">
        <div className="flex gap-3 flex-col sm:flex-row">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ex.: centro, sul, jardim, vila"
            className="min-w-0 flex-1 rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-2.5 text-white placeholder:text-white/30"
          />
          <div className="flex gap-3 sm:flex-none">
            <button
              type="button"
              className="flex-1 rounded-xl bg-[hsl(201,96%,45%)] px-4 py-2.5 text-sm font-medium text-white shadow-[0_4px_20px_hsl(201,96%,40%,0.3)] hover:brightness-110"
              onClick={() => load(query)}
            >
              Buscar
            </button>
            <button
              type="button"
              className="flex-1 rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/85 hover:bg-white/[0.08]"
              onClick={() => {
                setQuery("");
                load("");
              }}
            >
              Limpar
            </button>
          </div>
        </div>
      </GlassCard>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <MetricPill label="Total de estações" value={String(data.count || 0)} />
        <MetricPill label="Estações com chuva" value={String(rainSummary.raining)} />
        <MetricPill label="Chuva acumulada total" value={`${rainSummary.total} mm`} />
      </div>

      <GlassCard className="p-4 md:hidden space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Estações</h2>
            <p className="text-xs text-white/50">Toque no cabeçalho para ordenar.</p>
          </div>
          <div className="text-xs text-white/50">
            {SORTABLE_COLUMNS.find((item) => item.key === sortBy)?.label} {sortDirection}
          </div>
        </div>
        <div className="grid gap-2 grid-cols-2">
          {SORTABLE_COLUMNS.map((column) => (
            <button
              key={column.key}
              type="button"
              onClick={() => toggleSort(column.key)}
              className={`inline-flex items-center justify-between rounded-xl border px-3 py-2 text-sm shadow-none ${
                sortBy === column.key
                  ? "border-[hsl(201,96%,52%,0.3)] bg-[hsl(201,96%,52%,0.12)] text-[hsl(201,96%,72%)]"
                  : "border-white/[0.08] bg-white/[0.04] text-white/80"
              }`}
            >
              <span>{column.label}</span>
              <SortIcon active={sortBy === column.key} direction={sortDirection} type={column.type} />
            </button>
          ))}
        </div>
        {sortedItems.length === 0 ? (
          <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-10 text-center text-white/55">
            Nenhuma estação encontrada.
          </div>
        ) : (
          sortedItems.map((item) => (
            <div
              key={`${item.name}-${item.lat}-${item.lon}`}
              className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 space-y-3"
            >
              <div className="flex items-start justify-between gap-3">
                <strong className="text-sm leading-5 text-white">{item.name}</strong>
                <span className="rounded-full bg-[hsl(201,96%,52%,0.12)] px-2 py-1 text-xs font-mono-data text-[hsl(201,96%,72%)]">
                  {formatNumber(item.rain_day)} mm
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-white/45">Temperatura</p>
                  <strong className="font-mono-data text-white">{formatNumber(item.temp)} °C</strong>
                </div>
                <div>
                  <p className="text-xs text-white/45">Umidade</p>
                  <strong className="font-mono-data text-white">{formatNumber(item.humi, 0)}%</strong>
                </div>
                <div>
                  <p className="text-xs text-white/45">Vento</p>
                  <strong className="font-mono-data text-white">
                    {formatNumber(item.wind)} km/h {item.dire || ""}
                  </strong>
                </div>
                <div>
                  <p className="text-xs text-white/45">Rajada</p>
                  <strong className="font-mono-data text-white">{formatNumber(item.gust)} km/h</strong>
                </div>
                <div className="col-span-2">
                  <p className="text-xs text-white/45">Pressão</p>
                  <strong className="font-mono-data text-white">{formatNumber(item.pres, 0)} hPa</strong>
                </div>
              </div>
            </div>
          ))
        )}
      </GlassCard>

      <GlassCard className="hidden md:block overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-white/[0.05]">
              <tr className="text-left text-white/75">
                {SORTABLE_COLUMNS.map((column) => (
                  <th key={column.key} className="px-4 py-3 font-medium">
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={`inline-flex items-center gap-2 text-left shadow-none p-0 ${
                        sortBy === column.key ? "text-white" : "text-white/50"
                      }`}
                    >
                      <span>{column.label}</span>
                      <SortIcon active={sortBy === column.key} direction={sortDirection} type={column.type} />
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedItems.length === 0 ? (
                <tr>
                  <td colSpan="7" className="px-4 py-10 text-center text-white/55">
                    Nenhuma estação encontrada.
                  </td>
                </tr>
              ) : (
                sortedItems.map((item) => (
                  <tr key={`${item.name}-${item.lat}-${item.lon}`} className="border-t border-white/[0.06] text-white/85">
                    <td className="px-4 py-3 font-medium text-white">{item.name}</td>
                    <td className="px-4 py-3 font-mono-data">{formatNumber(item.rain_day)} mm</td>
                    <td className="px-4 py-3 font-mono-data">{formatNumber(item.temp)} °C</td>
                    <td className="px-4 py-3 font-mono-data">{formatNumber(item.humi, 0)}%</td>
                    <td className="px-4 py-3 font-mono-data">
                      {formatNumber(item.wind)} km/h {item.dire || ""}
                    </td>
                    <td className="px-4 py-3 font-mono-data">{formatNumber(item.gust)} km/h</td>
                    <td className="px-4 py-3 font-mono-data">{formatNumber(item.pres, 0)} hPa</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </LumiPage>
  );
}
