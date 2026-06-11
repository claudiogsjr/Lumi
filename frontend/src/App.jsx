import { BarChart3, ClipboardCheck, CloudSun, History, Info, Map, Menu, Moon, Radio, Sun, X } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getJson } from "./api";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useApiHealth } from "./hooks/useApiHealth";
import { cn } from "./lib/utils";
const AboutLumiPage = lazy(() => import("./pages/AboutLumiPage"));
const MapPage = lazy(() => import("./pages/MapPage"));
const ResultsPage = lazy(() => import("./pages/ResultsPage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const StationsPage = lazy(() => import("./pages/StationsPage"));
const UsabilityPage = lazy(() => import("./pages/UsabilityPage"));
const WeatherPage = lazy(() => import("./pages/WeatherPage"));

const navItems = [
  { to: "/", label: "Assistente Lumi", icon: CloudSun },
  { to: "/usability", label: "Avaliação", icon: ClipboardCheck },
  { to: "/stations", label: "Estações", icon: Radio },
  { to: "/map", label: "Mapa", icon: Map },
  { to: "/about", label: "Sobre a LUMI", icon: Info },
  { to: "/results", label: "Dashboard", icon: BarChart3 },
  { to: "/history", label: "Histórico", icon: History },
];

function Navigation({ mobile = false, onNavigate }) {
  return (
    <nav
      className={cn(
        "flex gap-1",
        mobile ? "flex-col p-2" : "flex-1 flex-col space-y-1 p-2",
      )}
    >
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors",
              isActive
                ? "bg-sidebar-accent text-sidebar-primary"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
            )
          }
        >
          <item.icon className="h-4 w-4" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function RouteFallback() {
  return (
    <div className="flex h-full min-h-[240px] items-center justify-center text-sm text-muted-foreground">
      Carregando...
    </div>
  );
}

export default function App() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [health, setHealth] = useState(null);
  const apiOnline = useApiHealth();
  const [theme, setTheme] = useState(() => window.localStorage.getItem("lumi-theme") || "dark");
  const location = useLocation();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme !== "dark");
    window.localStorage.setItem("lumi-theme", theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    const loadHealth = async () => {
      try {
        const data = await getJson("/api/system/health");
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth(null);
      }
    };

    loadHealth();
    const timer = window.setInterval(loadHealth, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const currentLabel = useMemo(
    () => navItems.find((item) => item.to === location.pathname)?.label || "Assistente Lumi",
    [location.pathname],
  );

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      <aside className="hidden md:flex w-[220px] shrink-0 h-screen bg-sidebar text-sidebar-foreground flex-col border-r border-sidebar-border">
        <div className="p-4 border-b border-sidebar-border flex items-center gap-2">
          <CloudSun className="h-5 w-5 text-sidebar-primary" />
          <div>
            <h1 className="text-sm font-semibold tracking-tight text-sidebar-primary-foreground">
              LUMI
            </h1>
            <p className="text-[10px] text-sidebar-foreground/60 uppercase tracking-widest">
              Assistente Inteligente de Monitoramento e Alerta Climático
            </p>
          </div>
        </div>
        <Navigation />
        <div className="px-3 pb-3">
          <div className="rounded border border-sidebar-border bg-sidebar-accent/30 p-3 space-y-2">
            <p className="text-[10px] text-sidebar-foreground/45 uppercase tracking-widest">
              Saúde da LUMI
            </p>
            <div className="grid gap-2 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sidebar-foreground/60">CPU</span>
                <strong className="text-sidebar-foreground">{health ? `${health.cpu_percent}%` : "--"}</strong>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sidebar-foreground/60">Memória</span>
                <strong className="text-sidebar-foreground">
                  {health ? `${health.memory_percent}%` : "--"}
                </strong>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sidebar-foreground/60">Disco</span>
                <strong className="text-sidebar-foreground">
                  {health ? `${health.disk_percent}%` : "--"}
                </strong>
              </div>
            </div>
            {health ? (
              <div className="pt-1 text-[10px] text-sidebar-foreground/45 space-y-1">
                <div>
                  RAM {health.memory_used_gb} / {health.memory_total_gb} GB
                </div>
                <div>
                  Disco {health.disk_used_gb} / {health.disk_total_gb} GB
                </div>
              </div>
            ) : null}
          </div>
        </div>
        <div className="px-3 pb-3">
          <button
            type="button"
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            className="w-full inline-flex items-center justify-center gap-2 rounded bg-sidebar-accent/60 px-3 py-2 text-xs text-sidebar-foreground hover:bg-sidebar-accent"
          >
            {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            {theme === "dark" ? "Tema claro" : "Tema escuro"}
          </button>
        </div>
        <div className="p-3 border-t border-sidebar-border">
          <p className="text-[10px] text-sidebar-foreground/40 text-center">
            Backend local em Python
          </p>
        </div>
      </aside>

      {!apiOnline && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-destructive text-destructive-foreground text-xs text-center py-1.5 px-4">
          ⚠️ Sem conexão com o servidor — verifique se o backend está em execução.
        </div>
      )}
      <main className="flex-1 overflow-hidden bg-background flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border md:hidden shrink-0">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-widest">LUMI</p>
            <h1 className="text-sm font-semibold">{currentLabel}</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
              className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-border bg-card text-foreground shadow-none"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={() => setMobileOpen((current) => !current)}
              className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-border bg-card text-foreground shadow-none"
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {mobileOpen && (
          <div className="md:hidden border-b border-border bg-sidebar text-sidebar-foreground">
            <Navigation mobile onNavigate={() => setMobileOpen(false)} />
          </div>
        )}

        <div className="flex-1 overflow-hidden min-h-0">
        <ErrorBoundary>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<WeatherPage />} />
            <Route path="/weather" element={<WeatherPage />} />
            <Route path="/usability" element={<UsabilityPage />} />
            <Route path="/stations" element={<StationsPage />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/about" element={<AboutLumiPage />} />
            <Route path="/results" element={<ResultsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
