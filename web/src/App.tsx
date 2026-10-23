import { AnimatePresence, motion } from "motion/react";
import { Mic, MicOff, Moon, RotateCcw, Send, Sun, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import {
  type BridgeEvent,
  type Card,
  type Health,
  getHealth,
  openEvents,
  resetDemo,
  sendTurn,
} from "./api";
import { BehindTheScenes } from "./BehindTheScenes";
import { CardView } from "./cards/CardView";
import { Logo } from "./Logo";
import { type Lang, type Listener, canListen, listen, speak, stopSpeaking } from "./speech";

type Member = "priya" | "lucia";
type Line = { who: "you" | "kilta"; text: string };

const MEMBERS: Record<Member, { name: string; lang: Lang }> = {
  priya: { name: "Priya", lang: "en" },
  lucia: { name: "Lucia", lang: "es" },
};

const CONNECT_LINE = "Hey Alexa, connect me to Kilta.";

function store(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: the setting just does not stick */
  }
}

function Segmented<T extends string>(props: {
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
  testPrefix: string;
  label: string;
}) {
  return (
    <div role="group" aria-label={props.label} className="flex rounded-full bg-clay-100 p-0.5 dark:bg-ink-700">
      {props.options.map((option) => (
        <button
          key={option.id}
          type="button"
          data-testid={`${props.testPrefix}-${option.id}`}
          aria-pressed={props.value === option.id}
          onClick={() => props.onChange(option.id)}
          className={`rounded-full px-3 py-1 text-sm font-semibold transition ${
            props.value === option.id
              ? "bg-clay-600 text-white shadow dark:bg-clay-500"
              : "text-ink-700 hover:bg-clay-200 dark:text-clay-100 dark:hover:bg-ink-800"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function IconButton(props: { label: string; onClick: () => void; children: React.ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      data-testid={props.testId}
      aria-label={props.label}
      title={props.label}
      onClick={props.onClick}
      className="flex h-9 w-9 items-center justify-center rounded-full bg-clay-100 text-ink-800 transition hover:bg-clay-200 dark:bg-ink-700 dark:text-clay-100 dark:hover:bg-ink-800"
    >
      {props.children}
    </button>
  );
}

export default function App() {
  const [stage, setStage] = useState<"title" | "device">("title");
  const [member, setMember] = useState<Member>("priya");
  const [lang, setLang] = useState<Lang>("en");
  const [dark, setDark] = useState(
    () => store("kilta.theme") === "dark" || (store("kilta.theme") === null && matchMedia("(prefers-color-scheme: dark)").matches),
  );
  const [muted, setMuted] = useState(() => store("kilta.mute") === "1");
  const [lines, setLines] = useState<Line[]>([]);
  const [card, setCard] = useState<Card | null>(null);
  const [cardKey, setCardKey] = useState(0);
  const [engineState, setEngineState] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [text, setText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [events, setEvents] = useState<BridgeEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const listener = useRef<Listener | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    save("kilta.theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    getHealth().then(setHealth);
    const close = openEvents(
      (event) =>
        setEvents((all) => (event.type === "reset" ? [event] : [...all, event].slice(-300))),
      setConnected,
    );
    return close;
  }, []);

  const say = useCallback(
    (speech: string, language: Lang) => {
      if (muted) return;
      speak(speech, language, () => setSpeaking(true), () => setSpeaking(false));
    },
    [muted],
  );

  const submit = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setNotice(null);
      stopSpeaking();
      setLines((all) => [...all, { who: "you", text: message }]);
      try {
        const response = await sendTurn(message, member, lang);
        setLines((all) => [...all, { who: "kilta", text: response.speech }]);
        if (response.card) {
          setCard(response.card);
          setCardKey((key) => key + 1);
        }
        setEngineState(response.state);
        setSessionId(response.session_id);
        setModel(response.model);
        if (response.error) setNotice("Kilta had trouble thinking. You can say that again.");
        say(response.speech, lang);
      } catch (error) {
        setNotice(`I can't reach the bridge. Is "make dev" running? (${(error as Error).message})`);
      } finally {
        busyRef.current = false;
        setBusy(false);
        getHealth().then(setHealth);
      }
    },
    [member, lang, say],
  );

  const start = () => {
    setStage("device");
    void submit(CONNECT_LINE);
  };

  const reset = async () => {
    stopSpeaking();
    try {
      await resetDemo();
      setLines([]);
      setCard(null);
      setEngineState(null);
      setSessionId(null);
      setModel(null);
      setNotice(null);
      setMember("priya");
      setLang("en");
    } catch (error) {
      setNotice(`Reset failed: ${(error as Error).message}`);
    }
  };

  const pickMember = (next: Member) => {
    setMember(next);
    setLang(MEMBERS[next].lang);
  };

  const startListening = () => {
    if (listener.current || busyRef.current) return;
    stopSpeaking();
    const started = listen(
      lang,
      (heard) => void submit(heard),
      () => {
        listener.current = null;
        setListening(false);
      },
    );
    if (!started) {
      setNotice("This browser can't listen. Use Chrome, or type below.");
      return;
    }
    listener.current = started;
    setListening(true);
  };
  const stopListening = () => listener.current?.stop();

  const onMicKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if ((event.key === " " || event.key === "Enter") && !event.repeat) {
      event.preventDefault();
      if (event.type === "keydown") startListening();
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const value = text;
    setText("");
    void submit(value);
  };

  const ringState = listening ? "listening" : busy ? "thinking" : speaking ? "speaking" : "idle";
  const ringColor = {
    listening: "rgba(220,38,38,0.65)",
    thinking: "rgba(217,119,6,0.65)",
    speaking: "rgba(63,143,120,0.7)",
    idle: "rgba(194,103,31,0.25)",
  }[ringState];

  if (stage === "title") {
    return (
      <main className="flex h-full items-center justify-center bg-gradient-to-br from-clay-100 via-clay-50 to-clay-200 p-6 dark:from-ink-900 dark:via-ink-800 dark:to-ink-900">
        <div className="flex max-w-2xl flex-col items-center gap-6 text-center">
          <Logo size={96} />
          <h1 className="text-7xl font-extrabold tracking-tight text-ink-900 dark:text-clay-50">Kilta</h1>
          <p className="text-2xl text-clay-700 dark:text-clay-200">Your home repair friend, on the kitchen floor with you.</p>
          <blockquote
            data-testid="wake-phrase"
            className="rounded-3xl border border-clay-200 bg-white/70 px-8 py-5 text-4xl font-semibold text-ink-900 shadow dark:border-ink-700 dark:bg-ink-800/80 dark:text-clay-50"
          >
            “Hey Alexa, connect me to Kilta.”
          </blockquote>
          <button
            type="button"
            data-testid="start"
            onClick={start}
            className="rounded-full bg-clay-600 px-10 py-4 text-2xl font-bold text-white shadow-lg transition hover:bg-clay-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-clay-500/50"
          >
            Start
          </button>
          <p className="text-sm text-ink-500 dark:text-clay-200/70">
            A simulated Alexa+ experience. Kilta is the real MCP server underneath. Fictional appliances only.
          </p>
        </div>
      </main>
    );
  }

  const lastLines = lines.slice(-2); // the last exchange; the full log is in the panel

  return (
    <div className="flex h-full items-stretch justify-center gap-4 p-4">
      <main
        data-testid="device"
        className="flex h-full min-h-0 w-full max-w-[980px] flex-col rounded-[2.2rem] bg-ink-900 p-3 shadow-2xl ring-1 ring-black/20 dark:bg-black"
      >
        <div className="flex min-h-0 flex-1 flex-col gap-3 rounded-[1.7rem] bg-clay-50 p-4 dark:bg-ink-900">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Logo size={32} />
              <span className="text-2xl font-extrabold text-ink-900 dark:text-clay-50">Kilta</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Segmented
                label="Who is speaking"
                testPrefix="member"
                value={member}
                onChange={pickMember}
                options={[
                  { id: "priya", label: "Priya" },
                  { id: "lucia", label: "Lucia" },
                ]}
              />
              <Segmented
                label="Language"
                testPrefix="lang"
                value={lang}
                onChange={setLang}
                options={[
                  { id: "en", label: "EN" },
                  { id: "es", label: "ES" },
                ]}
              />
              <IconButton
                label={muted ? "Unmute Kilta" : "Mute Kilta"}
                testId="mute"
                onClick={() => {
                  stopSpeaking();
                  setMuted(!muted);
                  save("kilta.mute", muted ? "0" : "1");
                }}
              >
                {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
              </IconButton>
              <IconButton label={dark ? "Light mode" : "Dark mode"} testId="theme" onClick={() => setDark(!dark)}>
                {dark ? <Sun size={18} /> : <Moon size={18} />}
              </IconButton>
              <button
                type="button"
                data-testid="reset"
                onClick={reset}
                className="flex h-9 items-center gap-1 rounded-full bg-clay-100 px-3 text-sm font-semibold text-ink-800 hover:bg-clay-200 dark:bg-ink-700 dark:text-clay-100 dark:hover:bg-ink-800"
              >
                <RotateCcw size={15} /> Demo reset
              </button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto pr-1" data-testid="card-area">
            <AnimatePresence mode="wait">
              <motion.div
                key={cardKey}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.22 }}
              >
                {card ? (
                  <CardView card={card} />
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-2 rounded-3xl border border-dashed border-clay-200 p-10 text-center text-2xl text-ink-500 dark:border-ink-700 dark:text-clay-200/70">
                    {busy ? "Connecting…" : "Hold the mic and talk, or type below."}
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {notice && (
            <p role="alert" className="rounded-2xl bg-amber-100 px-4 py-2 text-base text-amber-900 dark:bg-amber-900/30 dark:text-amber-100">
              {notice}
            </p>
          )}

          <div className="flex items-center gap-4 rounded-2xl bg-white/60 p-3 dark:bg-ink-800/70">
            <div
              data-testid="ring"
              data-ring={ringState}
              style={{ ["--ring" as string]: ringColor }}
              className={`h-14 w-14 shrink-0 rounded-full border-4 border-clay-500 bg-clay-100 dark:bg-ink-700 ${
                ringState === "idle" ? "" : "ring-live"
              }`}
            />
            <div data-testid="transcript" aria-live="polite" className="flex min-w-0 flex-1 flex-col gap-0.5 text-base">
              {lastLines.length === 0 && <span className="text-ink-500 dark:text-clay-200/70">Transcript</span>}
              {lastLines.map((line, index) => (
                <p
                  key={index}
                  data-who={line.who}
                  className={`truncate ${line.who === "you" ? "text-ink-500 dark:text-clay-200/80" : "font-semibold text-ink-900 dark:text-clay-50"}`}
                >
                  {line.who === "you" ? "You: " : "Kilta: "}
                  {line.text}
                </p>
              ))}
              {busy && (
                <p data-testid="thinking" className="text-clay-600 dark:text-clay-200">
                  Kilta is thinking…
                </p>
              )}
            </div>
          </div>

          <form onSubmit={onSubmit} className="flex items-center gap-2">
            <button
              type="button"
              data-testid="mic"
              aria-label="Hold to talk"
              aria-pressed={listening}
              disabled={!canListen()}
              title={canListen() ? "Hold to talk" : "Speech recognition needs Chrome"}
              onPointerDown={startListening}
              onPointerUp={stopListening}
              onPointerLeave={stopListening}
              onPointerCancel={stopListening}
              onKeyDown={onMicKey}
              onKeyUp={(event) => {
                if (event.key === " " || event.key === "Enter") stopListening();
              }}
              className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-white shadow transition focus:outline-none focus-visible:ring-4 focus-visible:ring-clay-500/50 disabled:bg-ink-500 ${
                listening ? "bg-red-600" : "bg-clay-600 hover:bg-clay-700"
              }`}
            >
              {canListen() ? <Mic size={26} /> : <MicOff size={26} />}
            </button>
            <input
              data-testid="text-input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={lang === "es" ? "Escribe a Kilta…" : "Type to Kilta…"}
              aria-label="Message to Kilta"
              autoComplete="off"
              className="h-14 min-w-0 flex-1 rounded-full border border-clay-200 bg-white px-5 text-xl text-ink-900 placeholder:text-ink-500 focus:outline-none focus-visible:ring-4 focus-visible:ring-clay-500/40 dark:border-ink-700 dark:bg-ink-800 dark:text-clay-50"
            />
            <button
              type="submit"
              data-testid="send"
              aria-label="Send"
              disabled={busy || !text.trim()}
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-clay-600 text-white shadow transition hover:bg-clay-700 disabled:opacity-40"
            >
              <Send size={24} />
            </button>
          </form>
        </div>
      </main>
      <div className="hidden h-full w-[19rem] shrink-0 lg:block 2xl:w-[24rem]">
        <BehindTheScenes
          events={events}
          state={engineState}
          sessionId={sessionId}
          model={model}
          health={health}
          connected={connected}
        />
      </div>
    </div>
  );
}
