import { CheckCircle2, ClipboardCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";
import RatingScale from "../components/RatingScale";
import { postJson } from "../api";

const STORAGE_KEY = "guardian-usability-state";

const initialState = {
  step: 1,
  sessionId: null,
  consentAccepted: false,
  survey: {
    q1: null,
    q2: null,
    q3: null,
    q4: null,
    q5: null,
    comment: "",
  },
};

const QUESTIONS = [
  ["q1", "A resposta foi clara e fácil de entender."],
  ["q2", "A resposta foi útil para o que eu precisava."],
  ["q3", "A resposta se adequou ao contexto da pergunta."],
  ["q4", "Foi fácil usar o sistema."],
  ["q5", "Minha satisfação geral com a experiência foi boa."],
];

function loadState() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? { ...initialState, ...JSON.parse(raw) } : initialState;
  } catch {
    return initialState;
  }
}

export default function UsabilityPage() {
  const [state, setState] = useState(loadState);
  const [status, setStatus] = useState("Aguardando consentimento.");
  const [loadingSurvey, setLoadingSurvey] = useState(false);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const progress = useMemo(() => `Etapa ${Math.min(state.step, 2)} de 2`, [state.step]);

  const resetEvaluation = () => {
    window.localStorage.removeItem(STORAGE_KEY);
    setState(initialState);
    setStatus("Avaliação limpa.");
  };

  const startSession = async () => {
    setStatus("Criando sessão...");
    try {
      const data = await postJson("/api/usability/session/start", {
        consent_accepted: true,
      });
      setState((current) => ({
        ...current,
        step: 2,
        sessionId: data.session_id,
        consentAccepted: true,
      }));
      setStatus("Consentimento registrado.");
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    }
  };

  const decline = () => {
    window.localStorage.removeItem(STORAGE_KEY);
    setState(initialState);
    setStatus("Fluxo encerrado.");
  };

  const updateSurvey = (key, value) => {
    setState((current) => ({
      ...current,
      survey: { ...current.survey, [key]: value },
    }));
  };

  const submitSurvey = async () => {
    if (!state.sessionId) {
      setStatus("Sessão de avaliação não iniciada.");
      return;
    }
    const { q1, q2, q3, q4, q5, comment } = state.survey;
    if (![q1, q2, q3, q4, q5].every(Boolean)) {
      setStatus("Responda todas as perguntas obrigatórias.");
      return;
    }

    setLoadingSurvey(true);
    setStatus("Enviando avaliação...");
    try {
      await postJson(`/api/usability/session/${state.sessionId}/survey`, {
        clarity_score: q1,
        usefulness_score: q2,
        adequacy_score: q3,
        ease_of_use_score: q4,
        satisfaction_score: q5,
        comment: comment || null,
      });
      await postJson(`/api/usability/session/${state.sessionId}/finish`, {});
      window.localStorage.removeItem(STORAGE_KEY);
      setState((current) => ({ ...current, step: 4 }));
      setStatus("Avaliação concluída.");
    } catch (error) {
      setStatus(`Erro: ${error.message}`);
    } finally {
      setLoadingSurvey(false);
    }
  };

  return (
    <LumiPage>
      <PageHeader
        title="Avaliação de usabilidade"
        description="Pesquisa de risco mínimo. Os dados são pseudonimizados e usados apenas para análise agregada da experiência com o assistente."
        badge={progress}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <MetricPill label="Sessão" value={state.sessionId ? state.sessionId.slice(0, 8) : "Aguardando"} />
        <MetricPill label="Consentimento" value={state.consentAccepted ? "Aceito" : "Pendente"} />
        <MetricPill label="Status" value={status} className="md:col-span-1" />
      </div>

      {state.step === 1 && (
        <GlassCard className="p-6 lg:p-7 space-y-5">
          <div className="flex items-center gap-3 text-[hsl(201,96%,72%)]">
            <ClipboardCheck className="h-5 w-5" />
            <span className="text-sm font-semibold uppercase tracking-[0.12em]">Consentimento</span>
          </div>
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-white">Participação na avaliação</h2>
            <p className="text-sm text-white/65">
              Antes de iniciar, confirme se aceita participar da avaliação.
              Não coletamos nome completo, CPF ou e-mail. Esta página contém apenas o termo de aceite e o questionário.
            </p>
          </div>
          <ul className="list-disc pl-5 text-sm text-white/60 space-y-2">
            <li>Você pode sair do fluxo a qualquer momento.</li>
            <li>As notas serão usadas apenas para pesquisa acadêmica.</li>
            <li>Os resultados serão analisados de forma agregada.</li>
          </ul>
          <div className="flex gap-3 flex-wrap">
            <button
              type="button"
              onClick={startSession}
              className="rounded-xl bg-[hsl(201,96%,45%)] px-4 py-2.5 text-sm font-medium text-white shadow-[0_4px_20px_hsl(201,96%,40%,0.3)] hover:brightness-110"
            >
              Aceito participar
            </button>
            <button
              type="button"
              className="rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/80 hover:bg-white/[0.08]"
              onClick={decline}
            >
              Não aceito
            </button>
          </div>
        </GlassCard>
      )}

      {state.step === 2 && (
        <GlassCard className="p-6 lg:p-7 space-y-5">
          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-[0.12em] text-white/40 font-semibold">
              Questionário
            </p>
            <h2 className="text-xl font-semibold text-white">Avalie sua experiência</h2>
            <p className="text-sm text-white/60">Responda usando a escala de 1 a 5.</p>
          </div>
          <div className="space-y-4">
            {QUESTIONS.map(([key, label]) => (
              <div key={key} className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-4">
                <RatingScale
                  label={label}
                  value={state.survey[key]}
                  onChange={(value) => updateSurvey(key, value)}
                  disabled={loadingSurvey}
                />
              </div>
            ))}
          </div>
          <div>
            <label className="block text-sm font-medium mb-2 text-white">Comentário opcional</label>
            <textarea
              rows={4}
              value={state.survey.comment}
              onChange={(event) => updateSurvey("comment", event.target.value)}
              placeholder="Escreva algo que ajude a interpretar sua avaliação."
              className="w-full rounded-xl border border-white/[0.08] bg-white/[0.04] px-4 py-3 text-sm text-white placeholder:text-white/30"
            />
          </div>
          <div className="flex gap-3 flex-wrap">
            <button
              type="button"
              onClick={submitSurvey}
              disabled={loadingSurvey}
              className="rounded-xl bg-[hsl(201,96%,45%)] px-4 py-2.5 text-sm font-medium text-white shadow-[0_4px_20px_hsl(201,96%,40%,0.3)] hover:brightness-110 disabled:opacity-60"
            >
              {loadingSurvey ? "Enviando..." : "Enviar avaliação"}
            </button>
            <button
              type="button"
              onClick={() => setState((current) => ({ ...current, step: 1 }))}
              disabled={loadingSurvey}
              className="rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/85 hover:bg-white/[0.08]"
            >
              Voltar ao aceite
            </button>
            <button
              type="button"
              onClick={resetEvaluation}
              disabled={loadingSurvey}
              className="rounded-xl border border-red-400/20 bg-red-500/10 px-4 py-2.5 text-sm text-red-100 hover:bg-red-500/15 disabled:opacity-60"
            >
              Limpar avaliação
            </button>
          </div>
        </GlassCard>
      )}

      {state.step === 4 && (
        <GlassCard className="p-6 lg:p-7 text-center space-y-3">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[hsl(201,96%,52%,0.12)]">
            <CheckCircle2 className="h-6 w-6 text-[hsl(201,96%,72%)]" />
          </div>
          <h2 className="text-xl font-semibold text-white">Obrigado pela participação.</h2>
          <p className="text-sm text-white/60">Sua avaliação foi registrada com sucesso.</p>
          <div className="pt-2">
            <button
              type="button"
              onClick={resetEvaluation}
              className="rounded-xl border border-white/[0.08] bg-white/[0.05] px-4 py-2.5 text-sm text-white/85 hover:bg-white/[0.08]"
            >
              Nova avaliação
            </button>
          </div>
        </GlassCard>
      )}

      <div className="text-xs text-white/45">{status}</div>
    </LumiPage>
  );
}
