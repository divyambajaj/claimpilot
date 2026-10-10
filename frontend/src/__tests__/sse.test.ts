import { describe, expect, it } from "vitest";
import { SSEParser, parseJSONData, type SSEMessage } from "../api/sse";

function collect(chunks: string[], end = false) {
  const out: SSEMessage[] = [];
  const p = new SSEParser((m) => out.push(m));
  chunks.forEach((c) => p.feed(c));
  if (end) p.end();
  return out;
}

describe("SSEParser", () => {
  it("parses named events with JSON data", () => {
    const [m] = collect(['event: stage\ndata: {"doc_id":"d1","stage":"extract"}\n\n']);
    expect(m.event).toBe("stage");
    expect(parseJSONData(m)).toEqual({ doc_id: "d1", stage: "extract" });
  });

  it("defaults event name to message and joins multi-line data", () => {
    const [m] = collect(["data: a\ndata: b\n\n"]);
    expect(m).toEqual({ event: "message", data: "a\nb" });
  });

  it("handles messages split across arbitrary chunk boundaries, including CRLF", () => {
    const raw = 'event: done\r\ndata: {"ok":true}\r\n\r\nevent: error\r\ndata: x\r\n\r\n';
    const chunks = raw.split("").reduce<string[]>((acc, ch, i) => (i % 3 === 0 ? [...acc, ch] : [...acc.slice(0, -1), acc[acc.length - 1] + ch]), []);
    const out = collect(chunks);
    expect(out.map((m) => m.event)).toEqual(["done", "error"]);
    expect(out[0].data).toBe('{"ok":true}');
  });

  it("ignores comments, keeps id and retry, skips events without data", () => {
    const out = collect([": keep-alive\n\nid: 7\nretry: 3000\nevent: x\ndata: 1\n\nevent: empty\n\n"]);
    expect(out).toEqual([{ event: "x", data: "1", id: "7", retry: 3000 }]);
  });

  it("strips only one leading space and flushes a trailing message on end()", () => {
    const out = collect(["data:  two spaces"], true);
    expect(out).toEqual([{ event: "message", data: " two spaces" }]);
  });

  it("returns undefined for non-JSON payloads", () => {
    expect(parseJSONData({ event: "m", data: "not json" })).toBeUndefined();
  });
});
