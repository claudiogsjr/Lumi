import { cn } from "../lib/utils";

export function LumiPage({ children, className }) {
  return (
    <div
      className={cn(
        "h-full overflow-y-auto relative text-slate-900 dark:text-white bg-[linear-gradient(135deg,#f7fbff_0%,#edf5ff_45%,#f8fafc_100%)] dark:bg-[linear-gradient(135deg,hsl(222,47%,11%)_0%,hsl(218,50%,15%)_40%,hsl(215,45%,10%)_100%)]",
        className,
      )}
    >
      <div className="absolute top-[-80px] left-[10%] w-[500px] h-[500px] rounded-full bg-[hsl(201,96%,52%,0.07)] blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-60px] right-[15%] w-[400px] h-[400px] rounded-full bg-[hsl(260,50%,45%,0.05)] blur-[100px] pointer-events-none" />
      <div className="relative z-10 w-full max-w-[1680px] mx-auto p-4 md:p-5 lg:p-6 xl:px-8 2xl:px-10 space-y-4">
        {children}
      </div>
    </div>
  );
}

export function GlassCard({ children, className, ...props }) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-slate-200/70 bg-white/75 backdrop-blur-2xl shadow-[0_4px_30px_rgba(15,23,42,0.08)] dark:border-white/[0.08] dark:bg-white/[0.04] dark:shadow-[0_4px_30px_rgba(0,0,0,0.25)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function PageHeader({ title, description, badge, extra }) {
  return (
    <GlassCard className="p-5 lg:p-6">
      <div className="flex items-start justify-between gap-4 flex-col lg:flex-row">
        <div className="space-y-2">
          <p className="text-[11px] text-slate-500 dark:text-white/40 uppercase tracking-[0.12em] font-semibold">
            LUMI
          </p>
          <h1 className="text-xl lg:text-2xl font-semibold text-slate-900 dark:text-white">{title}</h1>
          {description ? (
            <p className="text-sm text-slate-600 dark:text-white/60 max-w-3xl">{description}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {badge ? (
            <span className="rounded-full border border-[hsl(201,96%,52%,0.25)] bg-[hsl(201,96%,52%,0.12)] px-3 py-1 text-xs font-medium text-[hsl(201,96%,38%)] dark:text-[hsl(201,96%,72%)]">
              {badge}
            </span>
          ) : null}
          {extra}
        </div>
      </div>
    </GlassCard>
  );
}

export function MetricPill({ label, value, className }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-slate-200/70 bg-white/65 px-4 py-3 dark:border-white/[0.06] dark:bg-white/[0.03]",
        className,
      )}
    >
      <p className="text-[11px] text-slate-500 dark:text-white/38">{label}</p>
      <strong className="mt-1 block text-lg font-semibold text-slate-900 dark:text-white">{value}</strong>
    </div>
  );
}
