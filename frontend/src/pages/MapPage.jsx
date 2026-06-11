import L from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { getJson } from "../api";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";

function buildIcon(rain) {
  let color = "#22c55e";
  if (rain >= 50) color = "#dc2626";
  else if (rain >= 30) color = "#f97316";
  else if (rain >= 10) color = "#38bdf8";

  return L.divIcon({
    className: "custom-rain-marker",
    html: `
      <div style="
        width:18px;
        height:18px;
        border-radius:999px;
        background:${color};
        border:3px solid rgba(255,255,255,0.95);
        box-shadow:0 4px 10px rgba(15,23,42,0.25);
      "></div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function buildClusterIcon(cluster) {
  const count = cluster.getChildCount();
  let background = "linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%)";
  if (count >= 25) background = "linear-gradient(135deg, #f97316 0%, #fb923c 100%)";
  if (count >= 50) background = "linear-gradient(135deg, #dc2626 0%, #f87171 100%)";

  return L.divIcon({
    className: "lumi-cluster-icon",
    html: `
      <div style="
        width:46px;
        height:46px;
        border-radius:999px;
        display:flex;
        align-items:center;
        justify-content:center;
        background:${background};
        color:#ffffff;
        border:3px solid rgba(255,255,255,0.92);
        box-shadow:0 12px 26px rgba(15,23,42,0.28);
        font-size:13px;
        font-weight:700;
      ">${count}</div>
    `,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
}

function FitBounds({ items, selected }) {
  const map = useMap();

  useEffect(() => {
    if (selected?.lat != null && selected?.lon != null) {
      map.setView([Number(selected.lat), Number(selected.lon)], Math.min(Math.max(map.getZoom(), 10), 11));
      return;
    }
    const points = items
      .filter((item) => item.lat != null && item.lon != null)
      .map((item) => [Number(item.lat), Number(item.lon)]);
    if (points.length === 1) {
      map.setView(points[0], 10);
    } else if (points.length > 1) {
      map.fitBounds(points, { padding: [96, 96], maxZoom: 10 });
    }
  }, [items, map, selected]);

  return null;
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function inferRegion(name) {
  const text = String(name || "").toUpperCase();
  const regions = ["CENTRO", "NORTE", "SUL", "LESTE", "OESTE", "SUDESTE", "SUDOESTE", "NORDESTE", "NOROESTE"];
  return regions.find((region) => text.includes(region)) || "OUTROS";
}

export default function MapPage() {
  const [data, setData] = useState({ count: 0, items: [] });
  const [selected, setSelected] = useState(null);
  const [status, setStatus] = useState("Carregando mapa...");
  const [region, setRegion] = useState("");
  const [minRain, setMinRain] = useState("");
  const [minWind, setMinWind] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const result = await getJson("/api/stations");
        setData(result);
        setSelected(result.items?.[0] || null);
        setStatus(`OK: ${result.count} estações carregadas.`);
      } catch (error) {
        setStatus(`Erro: ${error.message}`);
      }
    })();
  }, []);

  const validItems = useMemo(
    () => (data.items || []).filter((item) => item.lat != null && item.lon != null),
    [data],
  );

  const regions = useMemo(() => {
    const values = Array.from(new Set(validItems.map((item) => inferRegion(item.name))));
    return values.sort();
  }, [validItems]);

  const filteredItems = useMemo(() => {
    return validItems.filter((item) => {
      const rain = Number(item.rain_day) || 0;
      const wind = Number(item.wind) || 0;
      if (region && inferRegion(item.name) !== region) return false;
      if (minRain !== "" && rain < Number(minRain)) return false;
      if (minWind !== "" && wind < Number(minWind)) return false;
      return true;
    });
  }, [validItems, region, minRain, minWind]);

  const defaultCenter = useMemo(() => {
    if (selected?.lat != null && selected?.lon != null) {
      return [Number(selected.lat), Number(selected.lon)];
    }
    if (filteredItems.length > 0) {
      return [Number(filteredItems[0].lat), Number(filteredItems[0].lon)];
    }
    return [-23.1896, -45.8841];
  }, [selected, filteredItems]);

  useEffect(() => {
    if (!selected && filteredItems.length > 0) {
      setSelected(filteredItems[0]);
      return;
    }
    if (
      selected &&
      !filteredItems.some((item) => item.name === selected.name && item.lat === selected.lat && item.lon === selected.lon)
    ) {
      setSelected(filteredItems[0] || null);
    }
  }, [filteredItems, selected]);

  return (
    <LumiPage>
      <PageHeader
        title="Mapa operacional"
        description="Mapa real com clusters, marcadores coloridos por chuva e filtros operacionais."
        badge={status}
      />

      <div className="grid gap-4 md:grid-cols-4">
        <MetricPill label="Estações visíveis" value={String(filteredItems.length)} />
        <MetricPill label="Filtro de região" value={region || "Todas"} />
        <MetricPill label="Chuva mínima" value={minRain !== "" ? `${minRain} mm` : "Sem corte"} />
        <MetricPill label="Vento mínimo" value={minWind !== "" ? `${minWind} km/h` : "Sem corte"} />
      </div>

      <GlassCard className="p-5 lg:p-6">
        <div className="grid gap-4 md:grid-cols-4">
          <label className="text-sm space-y-2">
            <span className="font-medium text-slate-900 dark:text-white">Região</span>
            <select
              value={region}
              onChange={(event) => setRegion(event.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-slate-900 dark:border-white/[0.08] dark:bg-white/[0.04] dark:text-white"
            >
              <option value="">Todas</option>
              {regions.map((item) => (
                <option key={item} value={item} className="text-black">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm space-y-2">
            <span className="font-medium text-slate-900 dark:text-white">Chuva mínima (mm)</span>
            <input
              type="number"
              min="0"
              value={minRain}
              onChange={(event) => setMinRain(event.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-slate-900 dark:border-white/[0.08] dark:bg-white/[0.04] dark:text-white"
            />
          </label>
          <label className="text-sm space-y-2">
            <span className="font-medium text-slate-900 dark:text-white">Vento mínimo (km/h)</span>
            <input
              type="number"
              min="0"
              value={minWind}
              onChange={(event) => setMinWind(event.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-slate-900 dark:border-white/[0.08] dark:bg-white/[0.04] dark:text-white"
            />
          </label>
          <div className="flex items-end">
            <button
              type="button"
              className="w-full rounded-xl border border-slate-200 bg-slate-100 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-200 dark:border-white/[0.08] dark:bg-white/[0.05] dark:text-white/85 dark:hover:bg-white/[0.08]"
              onClick={() => {
                setRegion("");
                setMinRain("");
                setMinWind("");
              }}
            >
              Limpar filtros
            </button>
          </div>
        </div>
        <div className="mt-4 flex gap-3 flex-wrap text-xs text-slate-600 dark:text-white/50">
          <span>Verde: baixa chuva</span>
          <span>Azul escuro: chuva moderada</span>
          <span>Laranja: chuva alta</span>
          <span>Vermelho: chuva crítica</span>
        </div>
      </GlassCard>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <GlassCard className="p-3">
          <div className="h-[700px] overflow-hidden rounded-2xl border border-slate-200 dark:border-white/[0.08] xl:h-[760px]">
            <MapContainer center={defaultCenter} zoom={10} scrollWheelZoom className="h-full w-full">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitBounds items={filteredItems} selected={selected} />
              <MarkerClusterGroup chunkedLoading iconCreateFunction={buildClusterIcon}>
                {filteredItems.map((item) => (
                  <Marker
                    key={`${item.name}-${item.lat}-${item.lon}`}
                    position={[Number(item.lat), Number(item.lon)]}
                    icon={buildIcon(Number(item.rain_day) || 0)}
                    eventHandlers={{ click: () => setSelected(item) }}
                  >
                    <Popup>
                      <div className="text-sm min-w-[180px]">
                        <strong>{item.name}</strong>
                        <div className="mt-2 space-y-1">
                          <div>Região: {inferRegion(item.name)}</div>
                          <div>Chuva: {formatNumber(item.rain_day)} mm</div>
                          <div>Temp: {formatNumber(item.temp)} °C</div>
                          <div>Umidade: {formatNumber(item.humi, 0)}%</div>
                          <div>
                            Vento: {formatNumber(item.wind)} km/h {item.dire || ""}
                          </div>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                ))}
              </MarkerClusterGroup>
            </MapContainer>
          </div>
        </GlassCard>

        <div className="space-y-4">
          <GlassCard className="p-5 lg:p-6">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">Estação selecionada</h2>
            {selected ? (
              <div className="mt-4 space-y-3">
                <div>
                  <p className="text-sm text-slate-500 dark:text-white/45">Nome</p>
                  <strong className="text-base text-slate-900 dark:text-white">{selected.name}</strong>
                </div>
                <div className="grid gap-3 grid-cols-2">
                  <MetricPill label="Região" value={inferRegion(selected.name)} />
                  <MetricPill label="Chuva" value={`${formatNumber(selected.rain_day)} mm`} />
                  <MetricPill label="Temperatura" value={`${formatNumber(selected.temp)} °C`} />
                  <MetricPill label="Umidade" value={`${formatNumber(selected.humi, 0)}%`} />
                  <MetricPill label="Vento" value={`${formatNumber(selected.wind)} km/h ${selected.dire || ""}`} />
                  <MetricPill label="Rajada" value={`${formatNumber(selected.gust)} km/h`} />
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-500 dark:text-white/55">Nenhuma estação selecionada.</p>
            )}
          </GlassCard>

          <GlassCard className="p-5 lg:p-6">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">Lista filtrada</h2>
            <div className="mt-4 space-y-2 max-h-[320px] overflow-y-auto xl:max-h-[420px]">
              {filteredItems.map((item) => (
                <button
                  key={`${item.name}-list`}
                  type="button"
                  onClick={() => setSelected(item)}
                  className={`w-full text-left rounded-xl border px-3 py-3 shadow-none ${
                    selected?.name === item.name
                      ? "border-[hsl(201,96%,52%,0.3)] bg-[hsl(201,96%,52%,0.12)]"
                      : "border-slate-200 bg-slate-50 dark:border-white/[0.08] dark:bg-white/[0.03]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <strong className="text-sm text-slate-900 dark:text-white">{item.name}</strong>
                    <span className="text-xs text-slate-500 dark:text-white/55 font-mono-data">
                      {formatNumber(item.rain_day)} mm
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-white/45">
                    {inferRegion(item.name)} · {formatNumber(item.wind)} km/h · {formatNumber(item.temp)} °C
                  </div>
                </button>
              ))}
              {filteredItems.length === 0 && (
                <p className="text-sm text-slate-500 dark:text-white/55">Nenhuma estação atende aos filtros.</p>
              )}
            </div>
          </GlassCard>
        </div>
      </div>
    </LumiPage>
  );
}
