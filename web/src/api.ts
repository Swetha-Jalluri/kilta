export const BRIDGE = (import.meta.env.VITE_BRIDGE_URL as string | undefined) ?? "http://localhost:8000";

export type Card = { type: string; [key: string]: any };

export type ToolCall = {
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  refused: boolean;
  reason: string | null;
  state: string | null;
  session_id: string | null;
  say: string | null;
  card_type?: string | null;
  ms: number;
  error: string | null;
};

export type TurnResponse = {
  speech: string;
  card: Card | null;
  tool_calls: ToolCall[];
  state: string | null;
  session_id: string | null;
  member_id: string | null;
  language: string;
  model: string | null;
  fallbacks: Record<string, unknown>[];
  elapsed_ms: number;
  error: string | null;
};

export type BridgeEvent = {
  seq: number;
  type: string;
  [key: string]: any;
};

export type Health = {
  status: string;
  mcp: { reachable: boolean; protocol_version?: string; tools?: string[]; error?: string };
  models: string[];
  demo_mode: boolean;
};

export async function sendTurn(text: string, member: string, language: string): Promise<TurnResponse> {
  const response = await fetch(`${BRIDGE}/api/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, member_id: member, language }),
  });
  if (!response.ok) throw new Error(`The bridge answered ${response.status}`);
  return response.json();
}

export async function resetDemo(): Promise<void> {
  const response = await fetch(`${BRIDGE}/api/reset`, {
    method: "POST",
    headers: { "X-Kilta-Demo": "1" },
  });
  if (!response.ok) throw new Error(`Reset failed (${response.status})`);
}

export async function getHealth(): Promise<Health | null> {
  try {
    const response = await fetch(`${BRIDGE}/api/health`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export function openEvents(onEvent: (event: BridgeEvent) => void, onState: (open: boolean) => void): () => void {
  const source = new EventSource(`${BRIDGE}/api/events?replay=50`);
  const types = ["turn_start", "tool_call", "turn_end", "model_retry", "model_fallback", "model_skipped", "model_empty", "reset"];
  for (const type of types) {
    source.addEventListener(type, (message) => onEvent(JSON.parse((message as MessageEvent).data)));
  }
  source.onopen = () => onState(true);
  source.onerror = () => onState(false);
  return () => source.close();
}
