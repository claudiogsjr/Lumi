import { BrainCircuit, CloudSun, GraduationCap, ShieldAlert, Sparkles, University, UserRound } from "lucide-react";
import { GlassCard, LumiPage, MetricPill, PageHeader } from "../components/LumiSurface";

const purposeItems = [
  "Facilitar o acesso a informações climáticas",
  "Apoiar ações de monitoramento e alerta",
  "Melhorar a interação com sistemas públicos",
  "Oferecer respostas claras em linguagem natural",
  "Contribuir com iniciativas ligadas à Defesa Civil e à prevenção",
];

const practicalItems = [
  "Responder perguntas sobre previsão do tempo",
  "Mostrar dados de estações meteorológicas em tempo real",
  "Explicar condições climáticas de forma simples",
  "Acelerar o acesso a informações relevantes para monitoramento",
];

const defenseItems = [
  "Apoio ao acompanhamento de condições climáticas",
  "Potencial de uso em cenários de atenção, prevenção e resposta",
  "Aproximação entre tecnologia e proteção da população",
];

function TextSection({ eyebrow, title, children }) {
  return (
    <GlassCard className="p-6 lg:p-7 space-y-4">
      <div className="space-y-2">
        <p className="text-[11px] uppercase tracking-[0.14em] text-[hsl(201,96%,52%)] font-semibold">{eyebrow}</p>
        <h2 className="text-xl lg:text-2xl font-semibold text-slate-900 dark:text-white">{title}</h2>
      </div>
      <div className="space-y-4 text-sm leading-7 text-slate-600 dark:text-white/70">{children}</div>
    </GlassCard>
  );
}

function BulletGrid({ items }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => (
        <div
          key={item}
          className="rounded-2xl border border-slate-200/80 bg-slate-50/90 px-4 py-4 text-sm text-slate-700 shadow-sm dark:border-white/[0.08] dark:bg-white/[0.03] dark:text-white/80"
        >
          {item}
        </div>
      ))}
    </div>
  );
}

function InstitutionalCard({ icon: Icon, title, highlight, children }) {
  return (
    <GlassCard className="p-5 lg:p-6 space-y-4">
      <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-[hsl(201,96%,52%,0.12)] text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
        <Icon className="h-5 w-5" />
      </div>
      <div className="space-y-2">
        <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500 dark:text-white/45 font-semibold">{title}</p>
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{highlight}</h3>
      </div>
      <div className="text-sm leading-7 text-slate-600 dark:text-white/70">{children}</div>
    </GlassCard>
  );
}

export default function AboutLumiPage() {
  return (
    <LumiPage>
      <PageHeader
        title="Conheça a LUMI"
        description="Assistente Inteligente de Monitoramento e Alerta Climático"
        badge="Institucional"
      />

      <GlassCard className="p-6 lg:p-8 overflow-hidden">
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr] items-center">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-[hsl(201,96%,52%,0.18)] bg-[hsl(201,96%,52%,0.1)] px-3 py-1 text-xs font-medium text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
              <Sparkles className="h-3.5 w-3.5" />
              Inovação aplicada ao serviço público
            </div>
            <div className="space-y-3">
              <h1 className="text-3xl lg:text-5xl font-semibold tracking-tight text-slate-900 dark:text-white">
                Conheça a LUMI
              </h1>
              <p className="text-lg lg:text-xl text-slate-600 dark:text-white/70 max-w-3xl">
                Assistente Inteligente de Monitoramento e Alerta Climático
              </p>
            </div>
            <p className="max-w-3xl text-sm lg:text-base leading-7 text-slate-600 dark:text-white/72">
              A LUMI nasceu de um projeto de dissertação voltado ao uso de inteligência artificial para ampliar o acesso a informações climáticas, apoiar ações de prevenção e resposta e aproximar dados técnicos da rotina das pessoas.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <MetricPill label="Base do projeto" value="Dissertação aplicada" />
            <MetricPill label="Foco" value="Defesa Civil e cidadão" />
            <MetricPill label="Abordagem" value="IA, usabilidade e serviço público" />
          </div>
        </div>
      </GlassCard>

      <div className="grid gap-4 xl:grid-cols-3">
        <GlassCard className="p-5 lg:p-6 space-y-3 xl:col-span-1">
          <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-[hsl(201,96%,52%,0.12)] text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
            <CloudSun className="h-5 w-5" />
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">O que é a LUMI</h3>
          <p className="text-sm leading-7 text-slate-600 dark:text-white/70">
            A LUMI é uma assistente virtual criada para interpretar perguntas em linguagem natural e responder sobre clima, previsão do tempo, monitoramento e dados de estações meteorológicas.
          </p>
          <p className="text-sm leading-7 text-slate-600 dark:text-white/70">
            Seu papel é tornar a consulta a informações meteorológicas mais simples, rápida e acessível, tanto para o cidadão quanto para contextos institucionais.
          </p>
        </GlassCard>

        <GlassCard className="p-5 lg:p-6 space-y-3 xl:col-span-1">
          <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-[hsl(201,96%,52%,0.12)] text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
            <BrainCircuit className="h-5 w-5" />
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Origem do projeto</h3>
          <p className="text-sm leading-7 text-slate-600 dark:text-white/70">
            A LUMI foi desenvolvida no contexto de uma dissertação sobre arquiteturas híbridas de assistentes virtuais. A proposta combina inteligência artificial e fluxos especializados para entregar respostas mais eficientes, auditáveis e adequadas a ambientes públicos e institucionais.
          </p>
        </GlassCard>

        <GlassCard className="p-5 lg:p-6 space-y-3 xl:col-span-1">
          <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-[hsl(201,96%,52%,0.12)] text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Aplicação pública</h3>
          <p className="text-sm leading-7 text-slate-600 dark:text-white/70">
            A LUMI conecta tecnologia, monitoramento e atendimento ao cidadão. Com isso, amplia o acesso a informações relevantes em situações de observação, prevenção e apoio à tomada de decisão.
          </p>
        </GlassCard>
      </div>

      <TextSection eyebrow="Desenvolvimento acadêmico" title="Desenvolvimento acadêmico do projeto">
        <p>
          A LUMI foi desenvolvida no contexto de um projeto de dissertação voltado à aplicação de inteligência artificial em soluções de monitoramento e atendimento ao cidadão. O projeto integra pesquisa aplicada, inovação tecnológica e interesse público, conectando arquitetura de assistentes virtuais, usabilidade e apoio a contextos de monitoramento climático e Defesa Civil.
        </p>
        <div className="grid gap-4 xl:grid-cols-3">
          <InstitutionalCard
            icon={UserRound}
            title="Desenvolvedor"
            highlight="Cláudio Generoso da Silva Júnior"
          >
            Desenvolvedor e pesquisador responsável pela concepção e desenvolvimento do projeto.
          </InstitutionalCard>

          <InstitutionalCard
            icon={GraduationCap}
            title="Orientação acadêmica"
            highlight="Ana Carolina Lorena"
          >
            Orientadora do projeto de dissertação.
          </InstitutionalCard>

          <InstitutionalCard
            icon={University}
            title="Instituições"
            highlight="ITA e UNIFESP"
          >
            <strong className="block text-slate-900 dark:text-white">ITA – Instituto Tecnológico de Aeronáutica</strong>
            <span className="block mt-2">
              UNIFESP – Universidade Federal de São Paulo
            </span>
          </InstitutionalCard>
        </div>
      </TextSection>

      <TextSection eyebrow="Propósito" title="Uma assistente pensada para uso real">
        <BulletGrid items={purposeItems} />
      </TextSection>

      <TextSection eyebrow="Como ajuda" title="O que a LUMI faz na prática">
        <BulletGrid items={practicalItems} />
      </TextSection>

      <TextSection eyebrow="Tecnologia com foco humano" title="Clareza, responsabilidade e utilidade pública">
        <p>
          Mais do que uma interface tecnológica, a LUMI foi pensada como uma ponte entre dados e pessoas. A proposta é usar inteligência artificial de forma responsável, transparente e útil, transformando informações técnicas em orientações mais acessíveis e compreensíveis.
        </p>
      </TextSection>

      <TextSection eyebrow="Defesa Civil" title="Monitoramento e prevenção mais próximos da população">
        <BulletGrid items={defenseItems} />
      </TextSection>

      <GlassCard className="p-6 lg:p-8 text-center space-y-4">
        <p className="text-[11px] uppercase tracking-[0.14em] text-[hsl(201,96%,52%)] font-semibold">Encerramento</p>
        <h2 className="text-2xl lg:text-3xl font-semibold text-slate-900 dark:text-white">
          Pesquisa aplicada com impacto público
        </h2>
        <p className="max-w-4xl mx-auto text-sm lg:text-base leading-7 text-slate-600 dark:text-white/70">
          A LUMI representa a convergência entre pesquisa aplicada, inteligência artificial e serviço público. Seu desenvolvimento mostra como soluções digitais podem ampliar o acesso à informação, fortalecer o monitoramento e aproximar tecnologia e cuidado com as pessoas.
        </p>
      </GlassCard>
    </LumiPage>
  );
}
