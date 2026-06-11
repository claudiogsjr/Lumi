import { Star } from "lucide-react";
import { cn } from "../lib/utils";

const LABELS = [
  "Discordo totalmente",
  "Discordo",
  "Neutro",
  "Concordo",
  "Concordo totalmente",
];

export default function RatingScale({ label, value, onChange, disabled = false }) {
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-white leading-snug">{label}</p>
      <div className="grid gap-2 sm:grid-cols-5">
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            key={score}
            type="button"
            disabled={disabled}
            onClick={() => onChange(score)}
            className={cn(
              "group relative flex flex-col items-center gap-1 rounded-lg px-2.5 py-2 transition-all duration-200",
              "hover:bg-[hsl(201,96%,52%,0.12)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(201,96%,52%,0.4)] shadow-none",
              value === score
                ? "bg-[hsl(201,96%,52%,0.15)] ring-1 ring-[hsl(201,96%,52%,0.35)]"
                : "bg-white/[0.04]",
              disabled && "opacity-60 pointer-events-none",
            )}
            aria-label={LABELS[score - 1]}
          >
            <Star
              className={cn(
                "h-5 w-5 transition-colors",
                value !== null && score <= value ? "fill-[hsl(201,96%,52%)] text-[hsl(201,96%,62%)]" : "text-white/30",
              )}
            />
            <span className="text-[10px] text-white/50 leading-tight text-center">
              {LABELS[score - 1]}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
