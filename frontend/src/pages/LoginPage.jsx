import { AlertCircle, CloudSun } from "lucide-react";
import { useEffect, useRef, useState } from "react";

function loadGoogleScript() {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-google-identity="true"]');
    if (existing) {
      if (window.google?.accounts?.id) resolve();
      else existing.addEventListener("load", () => resolve(), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.googleIdentity = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Falha ao carregar Google Identity Services."));
    document.head.appendChild(script);
  });
}

export default function LoginPage({ config, loading, error, onGoogleCredential }) {
  const buttonRef = useRef(null);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function setup() {
      if (!config?.google_client_id || !buttonRef.current) return;
      try {
        await loadGoogleScript();
        if (cancelled || !window.google?.accounts?.id) return;
        buttonRef.current.innerHTML = "";
        window.google.accounts.id.initialize({
          client_id: config.google_client_id,
          callback: async (response) => {
            try {
              setLocalError("");
              await onGoogleCredential(response.credential);
            } catch (err) {
              setLocalError(err.message || "Falha ao autenticar.");
            }
          },
        });
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: "filled_black",
          size: "large",
          type: "standard",
          shape: "pill",
          text: "signin_with",
          width: 320,
        });
      } catch (err) {
        if (!cancelled) setLocalError(err.message || "Falha ao carregar login Google.");
      }
    }

    setup();
    return () => {
      cancelled = true;
    };
  }, [config, onGoogleCredential]);

  return (
    <div
      className="min-h-[100dvh] flex items-center justify-center p-6 text-white"
      style={{
        background:
          "linear-gradient(135deg, hsl(222,47%,11%) 0%, hsl(218,50%,15%) 40%, hsl(215,45%,10%) 100%)",
      }}
    >
      <div className="absolute top-[-80px] left-[10%] w-[500px] h-[500px] rounded-full bg-[hsl(201,96%,52%,0.07)] blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-60px] right-[15%] w-[400px] h-[400px] rounded-full bg-[hsl(260,50%,45%,0.05)] blur-[100px] pointer-events-none" />
      <div className="relative z-10 w-full max-w-md rounded-3xl border border-white/[0.08] bg-white/[0.04] p-8 backdrop-blur-2xl shadow-[0_4px_30px_rgba(0,0,0,0.25)]">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[hsl(201,96%,52%,0.12)]">
            <CloudSun className="h-6 w-6 text-[hsl(201,96%,72%)]" />
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.12em] text-white/40 font-semibold">LUMI</p>
            <h1 className="text-xl font-semibold">Acesso restrito</h1>
          </div>
        </div>

        <p className="mt-5 text-sm leading-6 text-white/65">
          Entre com Google para acessar o painel. O backend valida a conta autorizada antes de liberar o uso.
        </p>

        <div className="mt-6 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4 text-sm text-white/70">
          <div className="font-medium text-white">Usuario autorizado</div>
          <div className="mt-1 break-all">{(config?.authorized_emails || ["claudio@ltecno.com.br"]).join(", ")}</div>
        </div>

        {!config?.google_enabled && !loading ? (
          <div className="mt-6 flex items-start gap-3 rounded-2xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-100">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>GOOGLE_CLIENT_ID nao configurado no backend.</div>
          </div>
        ) : null}

        {error || localError ? (
          <div className="mt-6 flex items-start gap-3 rounded-2xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-100">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>{error || localError}</div>
          </div>
        ) : null}

        <div className="mt-8 flex justify-center">
          {loading ? (
            <div className="text-sm text-white/55">Verificando sessao...</div>
          ) : (
            <div ref={buttonRef} />
          )}
        </div>
      </div>
    </div>
  );
}
