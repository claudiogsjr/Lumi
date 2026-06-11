import { ClipboardCheck, CloudSun, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { postJson } from "../api";
import ChatInput from "../components/ChatInput";
import ChatMessage from "../components/ChatMessage";
import InlineUsabilityRating from "../components/InlineUsabilityRating";

export default function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState("Pronto para interagir.");
  const [showRating, setShowRating] = useState(false);
  const scrollRef = useRef(null);
  const latestAssistantRef = useRef(null);

  // Fix iOS Safari keyboard: track both visual-viewport height AND its offsetTop
  // (how far the visual viewport has scrolled inside the layout viewport).
  // We use position:fixed + top:--vv-top on the root container so it always
  // sits exactly over the visible area — the keyboard can never push it off.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const update = () => {
      document.documentElement.style.setProperty("--vvh", `${vv.height}px`);
      document.documentElement.style.setProperty("--vv-top", `${vv.offsetTop}px`);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, []);

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
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const assistantCount = useMemo(
    () => messages.filter((item) => item.role === "assistant").length,
    [messages],
  );

  useEffect(() => {
    if (assistantCount >= 2 && !isLoading) {
      setShowRating(true);
    }
  }, [assistantCount, isLoading]);

  const handleSend = async (input) => {
    const userMsg = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setStatus("Consultando o backend local...");

    try {
      const data = await postJson("/chat", {
        user_id: "react_user",
        message: input,
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "Sem resposta",
          meta: {
            intent: data.intent || "-",
            decisionSource: data.decision_source || "-",
            latencyMs: data.latency_ms ?? null,
          },
        },
      ]);
      setStatus("Resposta recebida.");
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = () => {
    setMessages([]);
    setStatus("Histórico limpo.");
    setShowRating(false);
  };

  const isEmpty = messages.length === 0;

  return (
    <div
      className="flex flex-col"
      style={{
        position: "fixed",
        top: "var(--vv-top, 0px)",
        left: 0,
        right: 0,
        height: "var(--vvh, 100dvh)",
      }}
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0 bg-card">
        <div className="flex items-center gap-2">
          <CloudSun className="h-5 w-5 text-primary" />
          <div>
            <h1 className="text-sm font-semibold text-foreground">Assistente MeteoGuard</h1>
            <p className="text-[10px] text-muted-foreground">
              Pergunte sobre clima e estações meteorológicas
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {assistantCount >= 1 && (
            <button
              type="button"
              onClick={() => setShowRating(true)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors px-2 py-1 rounded hover:bg-muted shadow-none"
            >
              <ClipboardCheck className="h-3.5 w-3.5" />
              Avaliar
            </button>
          )}
          <button
            type="button"
            onClick={handleClear}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-muted shadow-none"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Limpar
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6 space-y-5">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full text-center gap-4">
            <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center">
              <CloudSun className="h-8 w-8 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">Olá. Sou o MeteoGuard.</h2>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                Seu assistente meteorológico da Defesa Civil. Pergunte sobre
                previsão do tempo, dados de estações em tempo real ou qualquer
                dúvida sobre o clima da região.
              </p>
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, index) => (
              <div
                key={index}
                ref={
                  msg.role === "assistant" && index === messages.length - 1
                    ? latestAssistantRef
                    : null
                }
              >
                <ChatMessage
                  role={msg.role}
                  content={msg.content}
                  meta={msg.meta}
                  isStreaming={isLoading && index === messages.length - 1 && msg.role === "assistant"}
                />
              </div>
            ))}
            {showRating && !isLoading && <InlineUsabilityRating messages={messages} />}
          </>
        )}
      </div>

      <div id="chat-input-bar" className="shrink-0 border-t border-border px-5 pt-4 pb-[calc(env(safe-area-inset-bottom,0px)+1rem)] bg-background/80 backdrop-blur">
        <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
          <span>{status}</span>
          <span>{assistantCount} respostas do assistente</span>
        </div>
        <ChatInput onSend={handleSend} isLoading={isLoading} showSuggestions={isEmpty} />
      </div>
    </div>
  );
}
