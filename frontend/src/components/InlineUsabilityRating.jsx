import { CheckCircle2 } from "lucide-react";
import { useMemo, useState } from "react";
import { postJson } from "../api";
import RatingScale from "./RatingScale";

const QUESTIONS = [
  ["clarity_score", "A resposta foi clara e fácil de entender."],
  ["usefulness_score", "A resposta foi útil para o que eu precisava."],
  ["adequacy_score", "A resposta se adequou ao contexto da pergunta."],
  ["ease_of_use_score", "Foi fácil usar este assistente."],
  ["satisfaction_score", "Minha satisfação geral com a experiência foi boa."],
];

function buildChatPairs(messages) {
  const pairs = [];
  let pendingUser = null;

  for (const message of messages) {
    if (message.role === "user") {
      pendingUser = message.content;
      continue;
    }
    if (message.role === "assistant" && pendingUser) {
      pairs.push({
        user_message: pendingUser,
        assistant_response: message.content,
        response_time_ms: message.meta?.latencyMs ?? null,
        route_or_intent: message.meta?.intent || null,
        had_rephrase: false,
      });
      pendingUser = null;
    }
  }

  return pairs;
}

export default function InlineUsabilityRating({ messages }) {
  const [scores, setScores] = useState({
    clarity_score: null,
    usefulness_score: null,
    adequacy_score: null,
    ease_of_use_score: null,
    satisfaction_score: null,
    comment: "",
  });
  const [status, setStatus] = useState("");
  const [sending, setSending] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const canSubmit = useMemo(
    () =>
      QUESTIONS.every(([key]) => Number.isInteger(scores[key]) && scores[key] >= 1 && scores[key] <= 5) &&
      !sending,
    [scores, sending],
  );

  const updateScore = (key, value) => {
    setScores((current) => ({ ...current, [key]: value }));
  };

  const handleSubmit = async () => {
    if (!canSubmit) {
      setStatus("Responda todas as perguntas antes de enviar.");
      return;
    }

    setSending(true);
    setStatus("Registrando avaliação...");

    try {
      const session = await postJson("/api/usability/session/start", {
        consent_accepted: true,
      });
      const sessionId = session.session_id;

      for (const pair of buildChatPairs(messages)) {
        await postJson(`/api/usability/session/${sessionId}/chat-log`, pair);
      }

      await postJson(`/api/usability/session/${sessionId}/survey`, {
        clarity_score: scores.clarity_score,
        usefulness_score: scores.usefulness_score,
        adequacy_score: scores.adequacy_score,
        ease_of_use_score: scores.ease_of_use_score,
        satisfaction_score: scores.satisfaction_score,
        comment: scores.comment || null,
      });

      await postJson(`/api/usability/session/${sessionId}/finish`, {});
      setSubmitted(true);
      setStatus("Avaliação registrada com sucesso.");
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    } finally {
      setSending(false);
    }
  };

  if (submitted) {
    return (
      <div className="mx-auto max-w-3xl">
        <div className="rounded-xl border border-border bg-card p-6 text-center shadow-sm space-y-3">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <CheckCircle2 className="h-6 w-6 text-primary" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">Avaliação registrada com sucesso</p>
            <p className="text-xs text-muted-foreground mt-1">
              Obrigado. Sua opinião foi vinculada a esta conversa para análise posterior.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="rounded-xl border border-border bg-card p-5 shadow-sm space-y-5">
        <div className="text-center space-y-1">
          <p className="text-sm font-semibold text-foreground">Como foi sua experiência?</p>
          <p className="text-xs text-muted-foreground">
            Avalie esta conversa. O fluxo usa o backend local já existente.
          </p>
        </div>

        <div className="space-y-4">
          {QUESTIONS.map(([key, label]) => (
            <RatingScale
              key={key}
              label={label}
              value={scores[key]}
              onChange={(value) => updateScore(key, value)}
              disabled={sending}
            />
          ))}
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Comentário opcional</label>
          <textarea
            rows={3}
            value={scores.comment}
            onChange={(event) => updateScore("comment", event.target.value)}
            placeholder="Se quiser, escreva um comentário curto sobre esta conversa."
            disabled={sending}
            className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm"
          />
        </div>

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <span className="text-xs text-muted-foreground">{status}</span>
          <button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {sending ? "Enviando..." : "Enviar avaliação"}
          </button>
        </div>
      </div>
    </div>
  );
}
