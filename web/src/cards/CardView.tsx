import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  EyeOff,
  FileText,
  Hand,
  HelpCircle,
  Home,
  Lock,
  Mail,
  PauseCircle,
  Search,
  ShieldAlert,
  ShieldCheck,
  Siren,
  Sparkles,
  Timer,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Card } from "../api";

type Tone = "calm" | "warn" | "danger" | "good";

const TONES: Record<Tone, string> = {
  calm: "text-clay-600 dark:text-clay-200",
  warn: "text-amber-600 dark:text-amber-300",
  danger: "text-alert dark:text-red-300",
  good: "text-sage dark:text-emerald-300",
};

function Shell(props: {
  variant?: string;
  card: Card;
  icon: ReactNode;
  kicker: string;
  title: string;
  tone?: Tone;
  children?: ReactNode;
}) {
  return (
    <section
      data-testid="card"
      data-card-type={props.card.type}
      data-variant={props.variant ?? ""}
      className="flex flex-col gap-3 rounded-3xl border border-clay-200 bg-white/70 p-5 shadow-sm dark:border-ink-700 dark:bg-ink-800/80"
    >
      <header className="flex items-center gap-3">
        <span className={`${TONES[props.tone ?? "calm"]} shrink-0`}>{props.icon}</span>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-widest text-ink-500 dark:text-clay-200/70">
            {props.kicker}
          </p>
          <h2 className="text-3xl font-bold leading-tight text-ink-900 dark:text-clay-50">{props.title}</h2>
        </div>
      </header>
      {props.children}
    </section>
  );
}

const Big = ({ children }: { children: ReactNode }) => (
  <p className="text-2xl leading-snug text-ink-800 dark:text-clay-100">{children}</p>
);

const Source = ({ source }: { source?: { manual_id: string; page: number } | null }) =>
  source ? (
    <span
      data-testid="source"
      className="inline-flex w-fit items-center gap-1 rounded-full bg-clay-100 px-3 py-1 text-sm font-medium text-clay-700 dark:bg-ink-700 dark:text-clay-200"
    >
      <FileText size={14} /> {source.manual_id} · page {source.page}
    </span>
  ) : null;

const Chip = ({ children, tone = "calm" }: { children: ReactNode; tone?: Tone }) => (
  <span
    className={`inline-flex items-center gap-1 rounded-full border border-current/30 px-3 py-1 text-sm font-semibold ${TONES[tone]}`}
  >
    {children}
  </span>
);

const Label = ({ children }: { children: ReactNode }) => (
  <kbd className="rounded-md border border-clay-200 bg-clay-50 px-2 py-0.5 font-mono text-base text-ink-800 dark:border-ink-700 dark:bg-ink-900 dark:text-clay-100">
    {children}
  </kbd>
);

function List({ items }: { items: ReactNode[] }) {
  return (
    <ol className="flex flex-col gap-2">
      {items.map((item, index) => (
        <li key={index} className="flex gap-3 text-xl text-ink-800 dark:text-clay-100">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-clay-100 text-base font-bold text-clay-700 dark:bg-ink-700 dark:text-clay-200">
            {index + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col rounded-2xl bg-clay-50 px-4 py-2 dark:bg-ink-900/60">
      <span className="text-xs font-semibold uppercase tracking-wider text-ink-500 dark:text-clay-200/70">{label}</span>
      <span className="text-xl font-semibold text-ink-900 dark:text-clay-50">{value}</span>
    </div>
  );
}

const money = (n: number) => `$${n.toFixed(2)}`;

export function CardView({ card }: { card: Card }) {
  switch (card.type) {
    case "household": {
      const speaker = card.speaker as { name: string; language: string; confidence: string } | null;
      const hh = card.household;
      return (
        <Shell card={card} icon={<Home size={34} />} kicker="Your household" title={speaker ? `Hi ${speaker.name}` : "Hi there"}>
          <Big>I know about {card.appliances?.length ?? 0} appliances in {hh?.name}.</Big>
          <div className="flex flex-wrap gap-2">
            {hh?.members?.map((m: any) => (
              <Chip key={m.id}>
                {m.name} · {m.language.toUpperCase()} · {m.confidence}
              </Chip>
            ))}
            {hh?.renter && <Chip>Renting · {hh.landlord?.name}</Chip>}
          </div>
        </Shell>
      );
    }
    case "safety_question":
      return (
        <Shell card={card} icon={<ShieldCheck size={34} />} kicker="Safety first" title="Quick safety check">
          {card.prior_stop && (
            <p className="rounded-2xl bg-amber-100 px-4 py-2 text-lg text-amber-900 dark:bg-amber-900/30 dark:text-amber-100">
              Earlier you reported {card.prior_stop.words?.join(", ") || "a safety problem"}. Has a professional checked it since?
            </p>
          )}
          <Big>Do you smell burning or gas, see smoke, sparks or flames, or feel a tingle or shock? Is there water near a plug or cord?</Big>
        </Shell>
      );
    case "safety_recheck":
      return (
        <Shell card={card} icon={<ShieldAlert size={34} />} kicker="Safety first" title="Is that happening now?" tone="warn">
          <Big>You mentioned something that could be unsafe. Is it happening right now? Please answer yes or no.</Big>
        </Shell>
      );
    case "safety_stop":
      return (
        <Shell card={card} icon={<Siren size={36} />} kicker="Stop" title="Please stop here" tone="danger">
          <List items={card.instructions ?? []} />
        </Shell>
      );
    case "appliance_list":
      return (
        <Shell card={card} icon={<Home size={34} />} kicker="Which appliance?" title="Your appliances">
          <ul className="flex flex-col gap-2">
            {(card.appliances ?? []).map((a: any, i: number) => (
              <li key={a.id ?? i} className="rounded-2xl bg-clay-50 px-4 py-3 text-xl dark:bg-ink-900/60">
                {typeof a === "string" ? a : `${a.name} · ${a.room}`}
              </li>
            ))}
          </ul>
        </Shell>
      );
    case "appliance":
      return (
        <Shell card={card} icon={<Home size={34} />} kicker="Is that the one?" title={card.name ?? "Your appliance"}>
          <div className="flex flex-wrap gap-2">
            {card.room && <Fact label="Room" value={card.room} />}
            {card.model_code && <Fact label="Model code" value={card.model_code} />}
          </div>
        </Shell>
      );
    case "quick_checks":
      return (
        <Shell card={card} icon={<ClipboardList size={34} />} kicker="Simple things first" title="Quick checks">
          <List
            items={(card.checks ?? []).map((c: any) => (
              <span key={c.id}>
                {c.text} {c.panel_labels?.map((l: string) => <Label key={l}>{l}</Label>)}
              </span>
            ))}
          />
          <Source source={{ manual_id: card.manual_id, page: card.page }} />
        </Shell>
      );
    case "ask_code":
      return (
        <Shell card={card} icon={<HelpCircle size={34} />} kicker="Read it to me" title="What does the screen show?">
          <Big>{card.entered ? `I don't see ${card.entered} in this manual.` : "Read the code one character at a time."}</Big>
          <div className="flex flex-wrap gap-2">
            {(card.known_codes ?? []).map((c: any) => (
              <Chip key={c.code}>{c.code} · {c.meaning}</Chip>
            ))}
          </div>
        </Shell>
      );
    case "diagnosis":
      return (
        <Shell card={card} icon={<Search size={34} />} kicker={`Error ${card.error_code}`} title={card.meaning ?? "Let's find the cause"}>
          {card.causes?.[0] && <Big>Most likely: {String(card.causes[0]).toLowerCase()}</Big>}
          <div className="flex flex-wrap gap-2">
            <Fact label="Fix" value={card.procedure} />
            <Fact label="Time" value={<span className="inline-flex items-center gap-1"><Timer size={18} />{card.minutes} min</span>} />
            <Fact label="You'll need" value={card.tools?.length ? card.tools.join(", ") : "No tools"} />
          </div>
          {card.repeat_count > 1 && <Chip tone="warn">Time number {card.repeat_count} for this code</Chip>}
          <Source source={card.source} />
        </Shell>
      );
    case "step": {
      const gate = card.gate as { prompt: string; kind: string; confirmed: boolean } | null;
      return (
        <Shell
          card={card}
          variant={card.text_withheld ? "withheld" : card.blocked ? "blocked" : gate && !gate.confirmed ? "gate" : "open"}
          icon={<Wrench size={34} />}
          kicker={`${card.title} · step ${card.step_number} of ${card.step_total}`}
          title={card.text_withheld ? "One moment" : `Step ${card.step_number}`}
        >
          <div className="h-2 overflow-hidden rounded-full bg-clay-100 dark:bg-ink-700">
            <div
              className="h-full rounded-full bg-clay-500 transition-all"
              style={{ width: `${(card.step_number / card.step_total) * 100}%` }}
            />
          </div>
          {card.text_withheld ? (
            <p data-testid="withheld" className="flex items-center gap-3 rounded-2xl bg-amber-100 px-4 py-4 text-2xl text-amber-900 dark:bg-amber-900/30 dark:text-amber-100">
              <EyeOff size={30} className="shrink-0" />
              <span>I'll tell you this step once you confirm the safety check below.</span>
            </p>
          ) : (
            <Big>
              {card.text} {card.panel_labels?.map((l: string) => <Label key={l}>{l}</Label>)}
            </Big>
          )}
          {gate && !gate.confirmed && (
            <p data-testid="gate" className="flex items-center gap-3 rounded-2xl border-2 border-amber-500 bg-amber-50 px-4 py-3 text-xl font-semibold text-amber-900 dark:bg-amber-900/20 dark:text-amber-100">
              <Lock size={26} className="shrink-0" />
              <span>Waiting for you: {gate.prompt}</span>
            </p>
          )}
          {gate?.confirmed && (
            <Chip tone="good"><CheckCircle2 size={16} /> Safety check confirmed</Chip>
          )}
          <Source source={card.source} />
        </Shell>
      );
    }
    case "paused":
      return (
        <Shell card={card} icon={<PauseCircle size={34} />} kicker="Paused" title={`Paused at step ${card.step_number} of ${card.step_total}`}>
          <Big>No hurry. Say "continue" when you're back.</Big>
        </Shell>
      );
    case "verify":
      return (
        <Shell card={card} icon={<Hand size={34} />} kicker="Last step" title="Did it work?">
          <Big>{card.verify}</Big>
          <Source source={card.source} />
        </Shell>
      );
    case "fixed": {
      const hc = card.health_card;
      return (
        <Shell card={card} icon={<Sparkles size={36} />} kicker="Fixed" title="You fixed it yourself" tone="good">
          {card.repeat_count > 1 && (
            <Chip tone="warn">Time number {card.repeat_count} for {card.error_code}: keep an eye on it</Chip>
          )}
          {hc && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-semibold uppercase tracking-wider text-ink-500 dark:text-clay-200/70">
                Health card · {hc.appliance.name}
              </p>
              {hc.repairs.slice(-3).map((r: any, i: number) => (
                <p key={i} className="rounded-2xl bg-clay-50 px-4 py-2 text-lg dark:bg-ink-900/60">
                  {r.date} · {r.error_code ?? "setting"} · {r.fix} <span className="text-ink-500">({r.outcome})</span>
                </p>
              ))}
            </div>
          )}
          {card.share_offer && <Chip>Want to share what worked, anonymously?</Chip>}
        </Shell>
      );
    }
    case "insight_shared":
      return (
        <Shell card={card} icon={<CheckCircle2 size={34} />} kicker="Thank you" title="Shared anonymously" tone="good">
          <Big>{card.model} · {card.error_code}. No names, no address.</Big>
        </Shell>
      );
    case "handoff":
      return (
        <Shell card={card} icon={<AlertTriangle size={34} />} kicker="Needs a technician" title="This one isn't a home fix" tone="warn">
          <Big>{card.reason}</Big>
          <div className="flex flex-wrap gap-2">
            {card.offers?.includes("technician_summary") && <Chip><ClipboardList size={16} /> Technician summary</Chip>}
            {card.offers?.includes("landlord_message") && <Chip><Mail size={16} /> Message to your landlord</Chip>}
          </div>
          <Source source={card.source} />
        </Shell>
      );
    case "technician_summary":
      return (
        <Shell card={card} icon={<ClipboardList size={34} />} kicker="For the technician · English" title={card.appliance ?? "Appliance"}>
          <div className="flex flex-wrap gap-2">
            {card.model_code && <Fact label="Model" value={card.model_code} />}
            {card.error_code && <Fact label="Error" value={`${card.error_code} · ${card.meaning ?? ""}`} />}
            {card.purchase_date && <Fact label="Bought" value={card.purchase_date} />}
          </div>
          {card.tried?.length > 0 && (
            <List items={card.tried.map((t: any) => `${t.title} (page ${t.page}): ${t.result === "fixed" ? "fixed it" : "did not fix it"}`)} />
          )}
          {card.reason && <Big>{card.reason}</Big>}
          {card.safety_notes && <p className="text-lg text-ink-500 dark:text-clay-200/70">{card.safety_notes}</p>}
        </Shell>
      );
    case "landlord_message":
      return (
        <Shell card={card} icon={<Mail size={34} />} kicker={`To ${card.to} · English`} title={card.subject}>
          <pre className="whitespace-pre-wrap rounded-2xl bg-clay-50 p-4 font-sans text-base leading-snug text-ink-800 dark:bg-ink-900/60 dark:text-clay-100">
            {card.body}
          </pre>
        </Shell>
      );
    case "health_card":
      return (
        <Shell card={card} icon={<ShieldCheck size={34} />} kicker="Health card" title={card.appliance?.name ?? "Appliance"}>
          <div className="flex flex-wrap gap-2">
            <Fact label="Bought" value={card.appliance?.purchase_date} />
            <Fact label="Warranty (estimate)" value={card.warranty?.in_warranty ? `until ${card.warranty.ends}` : `ended ${card.warranty?.ends}`} />
          </div>
          {card.repairs?.map((r: any, i: number) => (
            <p key={i} className="rounded-2xl bg-clay-50 px-4 py-2 text-lg dark:bg-ink-900/60">{r.date} · {r.error_code ?? "setting"} · {r.fix}</p>
          ))}
        </Shell>
      );
    case "warranty":
      return (
        <Shell card={card} icon={<ShieldCheck size={34} />} kicker="Warranty · estimate" title={card.appliance} tone={card.in_warranty ? "good" : "warn"}>
          <Big>{card.in_warranty ? "Probably still covered" : "Probably out of warranty"}: {card.coverage_months} months from {card.purchased}, ending {card.ends}.</Big>
        </Shell>
      );
    case "orders":
      return (
        <Shell card={card} icon={<ClipboardList size={34} />} kicker="Order history · simulated" title="Appliances you bought">
          <List items={(card.orders ?? []).map((o: any) => `${o.item} · ${o.date}`)} />
        </Shell>
      );
    case "cart":
      return (
        <Shell card={card} icon={<ClipboardList size={34} />} kicker="Parts cart · simulated" title={card.status === "created" ? "In your cart" : "Parts that fit"}>
          <List items={(card.parts ?? []).map((p: any) => `${p.name} · ${money(p.price_usd)}`)} />
          {card.total_usd != null && <Big>Total {money(card.total_usd)}. Nothing is bought in this demo.</Big>}
        </Shell>
      );
    case "insights":
      return (
        <Shell card={card} icon={<Sparkles size={34} />} kicker="Anonymous insights · synthetic" title="What others found">
          <List items={(card.entries ?? []).map((e: any) => `${e.model} ${e.error_code}: fixed at home ${e.fixed_at_home_pct}%`)} />
        </Shell>
      );
    case "consent":
      return (
        <Shell card={card} icon={<ShieldCheck size={34} />} kicker="Your choice" title="Is that okay?">
          <Big>{card.topic === "order_history" ? "Look through your order history, appliances only." : "Share the model, the code and the fix. Nothing else."}</Big>
        </Shell>
      );
    case "manual":
    case "manual_search":
      return (
        <Shell card={card} icon={<FileText size={34} />} kicker="Manual" title={card.title ?? "Manual search"}>
          <List items={(card.sections ?? card.results ?? []).map((s: any) => `${s.title} · page ${s.page}`)} />
        </Shell>
      );
    case "closed":
      return (
        <Shell card={card} icon={<CheckCircle2 size={34} />} kicker="All done" title="This repair is wrapped up">
          <Big>Want to start a new one?</Big>
        </Shell>
      );
    default:
      return (
        <Shell card={card} icon={<HelpCircle size={34} />} kicker="Kilta" title={card.type.replaceAll("_", " ")}>
          <pre className="overflow-auto rounded-2xl bg-clay-50 p-3 text-sm dark:bg-ink-900/60">{JSON.stringify(card, null, 2)}</pre>
        </Shell>
      );
  }
}
