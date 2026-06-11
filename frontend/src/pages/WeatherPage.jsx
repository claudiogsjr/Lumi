import {
  CloudLightning,
  CloudRain,
  CloudSun,
  Droplets,
  Eye,
  Send,
  Sun,
  Thermometer,
  Wind,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getJson, postJson } from "../api";
import lumiAvatar from "../assets/lumi-avatar.jpeg";
import lumiTransparent from "../assets/lumi-avatar-transparent.png";
import { GlassCard, LumiPage } from "../components/LumiSurface";
import { cn } from "../lib/utils";

function getWeatherIcon(rainfall, wind) {
  if ((Number(rainfall) || 0) > 50) return CloudLightning;
  if ((Number(rainfall) || 0) > 20) return CloudRain;
  if ((Number(rainfall) || 0) > 5 || (Number(wind) || 0) > 15) return CloudSun;
  return Sun;
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "0";
  return Number(value).toFixed(digits);
}

function getStatus(item) {
  const rain = Number(item?.rain_day) || 0;
  const wind = Math.max(Number(item?.wind) || 0, Number(item?.gust) || 0);
  if (rain >= 30 || wind >= 50) return "critical";
  if (rain >= 10 || wind >= 25) return "warning";
  return "normal";
}

function toStation(item, index) {
  return {
    id: `${item?.name || "station"}-${index}`,
    name: item?.name || `Estação ${index + 1}`,
    lat: Number(item?.lat),
    lon: Number(item?.lon),
    rainfall: Number(item?.rain_day) || 0,
    windSpeed: Number(item?.wind) || 0,
    gustSpeed: Number(item?.gust) || 0,
    rainfallAccum: Number(item?.rain_day) || 0,
    temperature: Number(item?.humi) || 0,
    airTemp: Number(item?.temp) || 0,
    pressure: Number(item?.pres) || 0,
    status: getStatus(item),
  };
}

function formatAssistantMessage(content) {
  const text = String(content || "").trim();
  if (!text) return "";
  return text.replace(/\n/g, "  \n");
}

export default function WeatherPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showSlowReplyHint, setShowSlowReplyHint] = useState(false);
  const [status, setStatus] = useState("Carregando dados meteorológicos...");
  const [stations, setStations] = useState([]);
  const [userLocation, setUserLocation] = useState(null);
  const scrollRef = useRef(null);
  const latestAssistantRef = useRef(null);
  const slowReplyTimerRef = useRef(null);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === "assistant" && latestAssistantRef.current) {
      latestAssistantRef.current.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      return;
    }

    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages]);

  useEffect(() => {
    return () => {
      if (slowReplyTimerRef.current) {
        window.clearTimeout(slowReplyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    const loadStations = async () => {
      try {
        const data = await getJson("/api/stations");
        if (!isMounted) return;
        setStations((data.items || []).map(toStation));
        // Nao sobrescreve o status durante uma conversa ativa — so atualiza o painel
        // quando nao ha mensagens (tela inicial) ou quando o status ainda e o de carregamento inicial.
        setStatus((prev) => {
          if (prev === "Carregando dados meteorológicos..." || prev === "Painel atualizado com dados das estações.") {
            return "Painel atualizado com dados das estações.";
          }
          return prev;
        });
      } catch (error) {
        if (!isMounted) return;
        setStatus((prev) => {
          // Nao sobrescreve status de conversa com erro de refresh do painel
          if (prev === "Carregando dados meteorológicos..." || prev === "Painel atualizado com dados das estações.") {
            return `Erro ao atualizar painel: ${error.message}`;
          }
          return prev;
        });
      }
    };

    loadStations();
    const timer = window.setInterval(loadStations, 60000);
    return () => {
      isMounted = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!("geolocation" in navigator)) return;

    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setUserLocation({
          lat: coords.latitude,
          lon: coords.longitude,
        });
      },
      () => {},
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 300000,
      },
    );
  }, []);

  const primaryStation = useMemo(() => {
    const validStations = stations.filter(
      (station) => Number.isFinite(station.lat) && Number.isFinite(station.lon),
    );

    if (!userLocation || validStations.length === 0) {
      return stations[0];
    }

    const toRadians = (value) => (value * Math.PI) / 180;
    const distanceKm = (a, b) => {
      const earthRadiusKm = 6371;
      const dLat = toRadians(b.lat - a.lat);
      const dLon = toRadians(b.lon - a.lon);
      const lat1 = toRadians(a.lat);
      const lat2 = toRadians(b.lat);
      const h =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
      return 2 * earthRadiusKm * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
    };

    return validStations
      .map((station) => ({
        ...station,
        distanceKm: distanceKm(userLocation, station),
      }))
      .sort((a, b) => a.distanceKm - b.distanceKm)[0];
  }, [stations, userLocation]);

  const secondaryStations = useMemo(
    () => stations.filter((station) => station.id !== primaryStation?.id),
    [stations, primaryStation],
  );

  const suggestions = ["Vai chover hoje?", "Como está as estações agora na região sul?", "Previsão para amanhã"];

  const handleSend = async (text) => {
    const message = (text ?? input).trim();
    if (!message || isLoading) return;

    const userMessage = { role: "user", content: message };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setShowSlowReplyHint(false);
    setStatus("Consultando o assistente...");
    slowReplyTimerRef.current = window.setTimeout(() => {
      setShowSlowReplyHint(true);
      setStatus("Essa pergunta pede um pouco mais de análise. Já estou verificando.");
    }, 1800);

    try {
      const data = await postJson("/chat", {
        user_id: "weather_panel_user",
        message,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "Sem resposta.",
        },
      ]);
      setStatus("Resposta recebida.");
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Desculpe, ocorreu um erro. Tente novamente.",
        },
      ]);
      setStatus(`Erro: ${error.message}`);
    } finally {
      if (slowReplyTimerRef.current) {
        window.clearTimeout(slowReplyTimerRef.current);
        slowReplyTimerRef.current = null;
      }
      setShowSlowReplyHint(false);
      setIsLoading(false);
    }
  };

  return (
    <LumiPage className="min-h-full flex flex-col">
      <div
        ref={scrollRef}
        className="relative z-10 flex-1 min-h-0 overflow-y-auto pb-[180px] md:pb-40"
      >
        <div className="space-y-4 w-full">
          <div className="relative flex items-start gap-0">
            <div className="hidden md:block relative z-20 shrink-0 -mr-6">
              <div className="relative">
                <div className="absolute inset-0 bg-[hsl(201,96%,52%,0.15)] blur-[60px] scale-[1.6] pointer-events-none" />
                <img
                  src={lumiTransparent}
                  alt="LUMI"
                  className="relative h-52 w-52 lg:h-60 lg:w-60 object-contain mix-blend-screen drop-shadow-[0_0_40px_hsl(201,96%,52%,0.3)] animate-[float_5s_ease-in-out_infinite]"
                />
              </div>
            </div>

            <div className="md:hidden relative z-20 shrink-0 mr-3">
              <div className="relative">
                <div className="absolute inset-0 bg-[hsl(201,96%,52%,0.12)] blur-[35px] scale-[1.5] pointer-events-none" />
                <img
                  src={lumiTransparent}
                  alt="LUMI"
                  className="relative h-28 w-28 object-contain mix-blend-screen drop-shadow-[0_0_20px_hsl(201,96%,52%,0.25)] animate-[float_4s_ease-in-out_infinite]"
                />
              </div>
            </div>

            <div className="flex-1 min-w-0 space-y-4 pt-2">
              {primaryStation && (
                <GlassCard className="p-5 lg:p-6">
                  <div className="flex items-start justify-between gap-4 flex-col lg:flex-row">
                    <div className="min-w-0">
                      <p className="text-[11px] text-white/40 uppercase tracking-[0.12em] font-semibold">
                        {primaryStation.name}
                      </p>
                      {primaryStation.distanceKm != null && (
                        <p className="text-[11px] text-[hsl(201,96%,72%)] font-medium mt-2">
                          Estação mais próxima  {formatNumber(primaryStation.distanceKm, 1)} km
                        </p>
                      )}
                    </div>

                    <div className="hidden lg:flex items-center gap-3 shrink-0">
                      {[
                        {
                          icon: Thermometer,
                          color: "text-violet-400",
                          bg: "bg-violet-500/10",
                          label: "Temperatura",
                          value: formatNumber(primaryStation.airTemp),
                          unit: "C",
                        },
                        {
                          icon: Droplets,
                          color: "text-blue-400",
                          bg: "bg-blue-500/10",
                          label: "Chuva",
                          value: formatNumber(primaryStation.rainfall),
                          unit: "mm",
                        },
                        {
                          icon: Eye,
                          color: "text-emerald-400",
                          bg: "bg-emerald-500/10",
                          label: "Umidade",
                          value: formatNumber(primaryStation.temperature, 0),
                          unit: "%",
                        },
                        {
                          icon: Wind,
                          color: "text-cyan-400",
                          bg: "bg-cyan-500/10",
                          label: "Vento",
                          value: formatNumber(primaryStation.windSpeed),
                          unit: "km/h",
                        },
                        {
                          icon: Wind,
                          color: "text-amber-400",
                          bg: "bg-amber-500/10",
                          label: "Rajada",
                          value: formatNumber(primaryStation.gustSpeed),
                          unit: "km/h",
                        },
                      ].map((stat) => (
                        <div
                          key={`top-${stat.label}`}
                          className="flex items-center gap-2.5 min-w-0 rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-3"
                        >
                          <div
                            className={cn(
                              "h-10 w-10 rounded-xl flex items-center justify-center shrink-0",
                              stat.bg,
                            )}
                          >
                            <stat.icon className={cn("h-4 w-4", stat.color)} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-[10px] text-white/30 font-medium">{stat.label}</p>
                            <p className="text-xs font-bold whitespace-nowrap">
                              {stat.value}
                              <span className="text-white/35 font-medium ml-0.5">{stat.unit}</span>
                            </p>
                          </div>
                        </div>
                      ))}

                      <div className="pt-1 self-start">
                        {(() => {
                          const Icon = getWeatherIcon(primaryStation.rainfall, primaryStation.windSpeed);
                          return (
                            <Icon className="h-16 w-16 lg:h-20 lg:w-20 text-amber-400 drop-shadow-[0_0_20px_rgba(251,191,36,0.3)]" />
                          );
                        })()}
                      </div>
                    </div>

                    <div className="pt-1 lg:hidden self-start">
                      {(() => {
                        const Icon = getWeatherIcon(primaryStation.rainfall, primaryStation.windSpeed);
                        return (
                          <Icon className="h-16 w-16 text-amber-400 drop-shadow-[0_0_20px_rgba(251,191,36,0.3)]" />
                        );
                      })()}
                    </div>
                  </div>

                  <div className="mt-5 pt-5 border-t border-white/[0.06]">
                    <div className="grid grid-cols-2 gap-3 md:hidden overflow-x-auto pb-1">
                      {[
                        {
                          icon: Thermometer,
                          color: "text-violet-400",
                          bg: "bg-violet-500/10",
                          label: "Temperatura",
                          value: formatNumber(primaryStation.airTemp),
                          unit: "C",
                        },
                        {
                          icon: Droplets,
                          color: "text-blue-400",
                          bg: "bg-blue-500/10",
                          label: "Chuva",
                          value: formatNumber(primaryStation.rainfall),
                          unit: "mm",
                        },
                        {
                          icon: Eye,
                          color: "text-emerald-400",
                          bg: "bg-emerald-500/10",
                          label: "Umidade",
                          value: formatNumber(primaryStation.temperature, 0),
                          unit: "%",
                        },
                        {
                          icon: Wind,
                          color: "text-cyan-400",
                          bg: "bg-cyan-500/10",
                          label: "Vento",
                          value: formatNumber(primaryStation.windSpeed),
                          unit: "km/h",
                        },
                        {
                          icon: Wind,
                          color: "text-amber-400",
                          bg: "bg-amber-500/10",
                          label: "Rajada",
                          value: formatNumber(primaryStation.gustSpeed),
                          unit: "km/h",
                        },
                      ].map((stat) => (
                        <div key={`mobile-${stat.label}`} className="flex items-center gap-2.5 min-w-0">
                          <div
                            className={cn(
                              "h-10 w-10 rounded-xl flex items-center justify-center shrink-0",
                              stat.bg,
                            )}
                          >
                            <stat.icon className={cn("h-4 w-4", stat.color)} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-[10px] text-white/30 font-medium">{stat.label}</p>
                            <p className="text-xs font-bold whitespace-nowrap">
                              {stat.value}
                              <span className="text-white/35 font-medium ml-0.5">{stat.unit}</span>
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="hidden md:block lg:hidden" />
                  </div>
                </GlassCard>
              )}
            </div>
          </div>

          <div className="space-y-3">
            {messages.length === 0 && (
              <div className="flex items-start gap-3">
                <div className="hidden md:block shrink-0 mt-1">
                  <div className="h-12 w-12 rounded-full overflow-hidden border border-white/10 shadow-lg">
                    <img src={lumiAvatar} alt="LUMI" className="h-full w-full object-cover" />
                  </div>
                </div>
                <div className="flex-1 space-y-2">
                  <GlassCard className="px-4 py-3">
                    <p className="text-sm text-white/75 leading-relaxed">
                      Olá! Sou a <span className="font-bold text-white">LUMI</span>, sua assistente da
                      Defesa Civil.
                      <br />
                      Pergunte sobre o clima, temperatura, chuva, vento ou estações e eu te ajudo.
                    </p>
                  </GlassCard>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => handleSend(suggestion)}
                        className="px-4 py-2 rounded-full text-xs font-medium bg-[hsl(201,96%,52%,0.12)] border border-[hsl(201,96%,52%,0.2)] hover:bg-[hsl(201,96%,52%,0.2)] hover:border-[hsl(201,96%,52%,0.35)] transition-all text-[hsl(201,96%,72%)] shadow-none"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <div
                key={index}
                ref={
                  message.role === "assistant" && index === messages.length - 1
                    ? latestAssistantRef
                    : null
                }
                className={cn("flex items-start gap-3", message.role === "user" ? "justify-end" : "")}
              >
                {message.role === "assistant" && (
                  <div className="hidden md:block shrink-0 mt-1">
                    <div className="h-10 w-10 rounded-full overflow-hidden border border-white/10 shadow-md">
                      <img src={lumiAvatar} alt="LUMI" className="h-full w-full object-cover" />
                    </div>
                  </div>
                )}
                <div
                  className={cn(
                    "max-w-[85%] md:max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                    message.role === "user"
                      ? "bg-[hsl(201,96%,45%)] text-white rounded-br-md shadow-[0_4px_20px_hsl(201,96%,40%,0.3)]"
                      : "bg-white/[0.05] border border-white/[0.08] text-white/90 rounded-bl-md",
                  )}
                >
                  {message.role === "assistant" ? (
                    <div className="prose prose-invert prose-sm max-w-none [&>p]:mb-2 [&>p:last-child]:mb-0 [&_strong]:text-white">
                      <ReactMarkdown>{formatAssistantMessage(message.content)}</ReactMarkdown>
                    </div>
                  ) : (
                    message.content
                  )}
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex items-start gap-3">
                <div className="hidden md:block shrink-0 mt-1">
                  <div className="h-10 w-10 rounded-full overflow-hidden border border-white/10 shadow-md">
                    <img src={lumiAvatar} alt="LUMI" className="h-full w-full object-cover" />
                  </div>
                </div>
                <div className="bg-white/[0.05] border border-white/[0.08] rounded-2xl rounded-bl-md px-4 py-3">
                  {showSlowReplyHint && (
                    <p className="mb-2 max-w-sm text-sm leading-relaxed text-white/80">
                      Essa pergunta pede um pouco mais de análise. Já estou verificando.
                    </p>
                  )}
                  <div className="flex gap-1.5">
                    <div className="w-2 h-2 rounded-full bg-white/40 animate-bounce [animation-delay:0ms]" />
                    <div className="w-2 h-2 rounded-full bg-white/40 animate-bounce [animation-delay:150ms]" />
                    <div className="w-2 h-2 rounded-full bg-white/40 animate-bounce [animation-delay:300ms]" />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 md:sticky md:z-20 md:px-6 md:pb-6">
        <div className="mx-auto w-full max-w-[1680px] space-y-2 rounded-t-3xl border-t border-white/[0.08] bg-[linear-gradient(180deg,rgba(15,23,42,0.15)_0%,rgba(15,23,42,0.78)_24%,rgba(15,23,42,0.96)_100%)] px-1 pt-4 backdrop-blur-xl md:rounded-2xl md:border-t-0 md:bg-[linear-gradient(180deg,rgba(15,23,42,0)_0%,rgba(15,23,42,0.38)_18%,rgba(15,23,42,0.85)_100%)] dark:bg-[linear-gradient(180deg,rgba(15,23,42,0.15)_0%,rgba(15,23,42,0.78)_24%,rgba(15,23,42,0.96)_100%)] md:dark:bg-[linear-gradient(180deg,rgba(15,23,42,0)_0%,rgba(15,23,42,0.38)_18%,rgba(15,23,42,0.85)_100%)]">
          <div className="px-2 text-xs text-white/45 md:px-1">{status}</div>
          <GlassCard className="flex items-center gap-3 p-2.5 pl-4 md:pl-5 border-white/[0.1]">
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && handleSend()}
              placeholder="Pergunte sobre chuva, temperatura ou estações..."
              className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-white/25 outline-none"
              disabled={isLoading}
            />

            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || isLoading}
              className={cn(
                "h-11 w-11 rounded-xl flex items-center justify-center transition-all shrink-0 shadow-none",
                input.trim()
                  ? "bg-[hsl(201,96%,45%)] text-white shadow-[0_4px_20px_hsl(201,96%,45%,0.35)] hover:brightness-110"
                  : "bg-white/[0.05] text-white/25",
              )}
            >
              <Send className="h-4 w-4" />
            </button>
          </GlassCard>
        </div>
      </div>
    </LumiPage>
  );
}
