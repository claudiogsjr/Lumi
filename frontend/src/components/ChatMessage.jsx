import { Bot, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { cn } from "../lib/utils";

export default function ChatMessage({
  role,
  content,
  isStreaming = false,
  meta,
}) {
  const isUser = role === "user";
  const detailItems = [
    meta?.intent ? `Intent ${meta.intent}` : null,
    meta?.decisionSource ? `Source ${meta.decisionSource}` : null,
    meta?.latencyMs ? `${meta.latencyMs} ms` : null,
  ].filter(Boolean);

  return (
    <div className={cn("flex gap-3 max-w-3xl", isUser ? "ml-auto flex-row-reverse" : "")}>
      <div
        className={cn(
          "h-8 w-8 rounded-full flex items-center justify-center shrink-0 mt-1",
          isUser ? "bg-[hsl(201,96%,45%)] text-white" : "bg-white/[0.06] text-white/70",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div className={cn("flex flex-col gap-1 min-w-0", isUser ? "items-end" : "items-start")}>
        <div className="flex items-center gap-2 px-1 text-[11px] text-white/45">
          <span>{isUser ? "Você" : "Assistente"}</span>
          {detailItems.length > 0 && <span>{detailItems.join(" · ")}</span>}
        </div>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed max-w-[620px]",
            isUser
              ? "bg-[hsl(201,96%,45%)] text-white rounded-tr-sm shadow-[0_4px_20px_hsl(201,96%,40%,0.3)]"
              : "bg-white/[0.05] border border-white/[0.08] text-white/90 rounded-tl-sm shadow-sm",
          )}
        >
          {isUser ? (
            <p>{content}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-li:my-0.5 prose-headings:my-2">
              <ReactMarkdown>{content}</ReactMarkdown>
              {isStreaming && (
                <span className="inline-block w-1.5 h-4 bg-[hsl(201,96%,52%,0.6)] animate-pulse ml-0.5 align-text-bottom rounded-sm" />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
