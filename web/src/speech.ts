// Web Speech API: push-to-talk recognition and spoken replies. Everything degrades quietly when
// the browser has no support (the text box always works).

export const LANGS = { en: "en-US", es: "es-ES" } as const;
export type Lang = keyof typeof LANGS;

type RecognitionCtor = new () => any;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canListen = (): boolean => recognitionCtor() !== null;
export const canSpeak = (): boolean => "speechSynthesis" in window;

export type Listener = { stop: () => void };

/** Start listening. Calls onFinal once with what was heard (empty if nothing). */
export function listen(lang: Lang, onFinal: (text: string) => void, onEnd: () => void): Listener | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const recognition = new Ctor();
  recognition.lang = LANGS[lang];
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  let heard = "";
  recognition.onresult = (event: any) => {
    for (const result of event.results) heard += result[0].transcript + " ";
  };
  recognition.onend = () => {
    if (heard.trim()) onFinal(heard.trim());
    onEnd();
  };
  recognition.onerror = () => onEnd();
  try {
    recognition.start();
  } catch {
    return null;
  }
  return { stop: () => recognition.stop() };
}

/** The best installed voice for a language: es-ES or es-MX for Spanish, en-US or en-GB for English. */
export function pickVoice(lang: Lang, voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const prefer = lang === "es" ? ["es-ES", "es-MX", "es-US"] : ["en-US", "en-GB"];
  const norm = (value: string) => value.replace("_", "-").toLowerCase();
  for (const tag of prefer) {
    const exact = voices.find((voice) => norm(voice.lang) === tag.toLowerCase());
    if (exact) return exact;
  }
  return voices.find((voice) => norm(voice.lang).startsWith(lang)) ?? null;
}

export function speak(text: string, lang: Lang, onStart: () => void, onEnd: () => void): void {
  if (!canSpeak() || !text) return onEnd();
  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = LANGS[lang];
    const voice = pickVoice(lang, window.speechSynthesis.getVoices());
    if (voice) utterance.voice = voice;
    utterance.rate = 0.95;
    utterance.onstart = onStart;
    utterance.onend = onEnd;
    utterance.onerror = onEnd;
    window.speechSynthesis.speak(utterance);
  } catch {
    onEnd(); // speaking is a bonus; the card and the transcript still show everything
  }
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}
