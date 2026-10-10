/**
 * Minimal Server-Sent Events support.
 *
 * `SSEParser` is a pure, incremental parser (feed it arbitrary chunks, it emits complete messages).
 * `openSSE` streams a URL with fetch so we can parse with the same code everywhere and abort cleanly.
 */

export interface SSEMessage {
  event: string; // defaults to "message"
  data: string;
  id?: string;
  retry?: number;
}

export class SSEParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | undefined;
  private retry: number | undefined;

  constructor(private readonly onMessage: (msg: SSEMessage) => void) {}

  feed(chunk: string): void {
    this.buffer += chunk;
    // A trailing "\r" may be the first half of a "\r\n" split across chunks: hold it back.
    let held = "";
    if (this.buffer.endsWith("\r")) {
      held = "\r";
      this.buffer = this.buffer.slice(0, -1);
    }
    // Split on any line terminator; keep the trailing partial line in the buffer.
    const lines = this.buffer.split(/\r\n|\r|\n/);
    this.buffer = (lines.pop() ?? "") + held;
    for (const line of lines) this.processLine(line);
  }

  /** Flush at end of stream; a final message without a blank line is dispatched. */
  end(): void {
    const rest = this.buffer.replace(/\r$/, "");
    if (rest) {
      this.processLine(rest);
      this.buffer = "";
    }
    this.dispatch();
  }

  private processLine(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) return; // comment / keep-alive
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    let value = idx === -1 ? "" : line.slice(idx + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        this.event = value;
        break;
      case "data":
        this.data.push(value);
        break;
      case "id":
        if (!value.includes("\0")) this.id = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) this.retry = Number(value);
        break;
      default:
        break; // unknown fields are ignored per spec
    }
  }

  private dispatch(): void {
    if (this.data.length === 0) {
      this.event = "";
      return;
    }
    const msg: SSEMessage = { event: this.event || "message", data: this.data.join("\n") };
    if (this.id !== undefined) msg.id = this.id;
    if (this.retry !== undefined) msg.retry = this.retry;
    this.event = "";
    this.data = [];
    this.onMessage(msg);
  }
}

/** Parse the `data` payload as JSON; returns undefined for non-JSON payloads. */
export function parseJSONData<T = unknown>(msg: SSEMessage): T | undefined {
  try {
    return JSON.parse(msg.data) as T;
  } catch {
    return undefined;
  }
}

export interface OpenSSEOptions {
  headers?: Record<string, string>;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

/** Open an SSE stream with fetch. Returns a function that closes the stream. */
export function openSSE(url: string, onMessage: (msg: SSEMessage) => void, opts: OpenSSEOptions = {}): () => void {
  const controller = new AbortController();
  const parser = new SSEParser(onMessage);

  (async () => {
    try {
      const res = await fetch(url, {
        headers: { Accept: "text/event-stream", ...opts.headers },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`SSE ${res.status} ${res.statusText}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, { stream: true }));
      }
      parser.end();
      opts.onClose?.();
    } catch (err) {
      if (controller.signal.aborted) return;
      opts.onError?.(err);
    }
  })();

  return () => controller.abort();
}
