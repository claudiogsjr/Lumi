import { useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";
import { cn } from "../lib/utils";

const DEFAULT_SUGGESTIONS = [
  "Vai chover hoje em São José dos Campos?",
  "Como está a estação do Centro?",
  "Qual a previsão para amanhã?",
  "Está ventando forte em alguma região?",
];

export default function ChatInput({
  onSend,
  isLoading,
  showSuggestions = false,
  suggestions = DEFAULT_SUGGESTIONS,
  placeholder = "Pergunte sobre o clima ou estações meteorológicas...",
}) {
  const [input, setInput] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
  }, [input]);

  const handleSend = (message = input) => {
    const trimmed = message.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setInput("");
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto space-y-3">
      {showSuggestions && (
        <div className="flex flex-wrap gap-2 justify-center px-4">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => handleSend(suggestion)}
              disabled={isLoading}
              className="text-xs rounded-full px-3 py-1.5 border border-[hsl(201,96%,52%,0.2)] bg-[hsl(201,96%,52%,0.1)] text-[hsl(201,96%,72%)] hover:bg-[hsl(201,96%,52%,0.18)] transition-colors disabled:opacity-50 shadow-none"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.04] px-4 py-2 shadow-sm backdrop-blur-xl">
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          className="flex-1 resize-none bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none py-1.5 max-h-[120px]"
        />
        <button
          type="button"
          onClick={() => handleSend()}
          disabled={!input.trim() || isLoading}
          className={cn(
            "h-8 w-8 rounded-full flex items-center justify-center transition-colors shrink-0 shadow-none p-0",
            input.trim() && !isLoading
              ? "bg-[hsl(201,96%,45%)] text-white hover:brightness-110"
              : "bg-white/[0.06] text-white/30",
          )}
        >
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}
