import { useRef, useState, type DragEvent } from "react";
import { Paperclip, Upload } from "lucide-react";

const ACCEPT = "image/png,image/jpeg,image/webp,image/heic,application/pdf";
const MAX_BYTES = 10 * 1024 * 1024;

interface Props {
  onFiles: (files: File[]) => void;
  onSamples: () => void;
  compact?: boolean;
  disabled?: boolean;
}

export function DropZone({ onFiles, onSamples, compact, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  function take(list: FileList | null) {
    if (!list) return;
    const all = Array.from(list);
    const ok = all.filter((f) => (f.type.startsWith("image/") || f.type === "application/pdf") && f.size <= MAX_BYTES).slice(0, 10);
    const skipped = all.length - ok.length;
    setNote(skipped ? `${skipped} file${skipped > 1 ? "s" : ""} skipped: images or PDFs up to 10 MB, 10 at a time.` : null);
    if (ok.length) onFiles(ok);
  }

  const drag = {
    onDragOver: (e: DragEvent) => {
      e.preventDefault();
      if (!disabled) setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setOver(false);
      if (!disabled) take(e.dataTransfer.files);
    },
  };

  const picker = (
    <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" onChange={(e) => (take(e.target.files), (e.target.value = ""))} tabIndex={-1} aria-hidden />
  );

  if (compact) {
    return (
      <div>
      <div {...drag} className={`card flex items-center gap-2 px-2 py-2 transition-colors ${over ? "border-accent bg-accent-soft" : ""}`}>
        {picker}
        <button type="button" className="btn-ghost" onClick={() => input.current?.click()} disabled={disabled}>
          <Paperclip size={16} strokeWidth={1.5} /> Add files
        </button>
        <span className="hidden flex-1 text-sm text-ink-3 sm:block">{over ? "Drop to add to this claim" : "or drop receipts, PDFs and UPI screenshots here"}</span>
        <span className="flex-1 sm:hidden" />
        <button type="button" className="btn-secondary" onClick={onSamples} disabled={disabled}>
          Sample receipts
        </button>
      </div>
      {note && <p className="mt-1.5 text-xs text-warn" role="status">{note}</p>}
      </div>
    );
  }

  return (
    <div>
      <div
        {...drag}
        className={`flex flex-col items-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${over ? "border-accent bg-accent-soft" : "border-line-strong bg-surface"}`}
      >
        {picker}
        <Upload size={20} strokeWidth={1.5} className="text-ink-3" />
        <p className="mt-3 text-md font-medium text-ink">Drop receipts here</p>
        <p className="mt-1 max-w-sm text-sm text-ink-3">Photos, PDFs and UPI screenshots. Up to 10 files, 10 MB each.</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <button type="button" className="btn-primary" onClick={() => input.current?.click()} disabled={disabled}>
            Choose files
          </button>
          <button type="button" className="btn-secondary" onClick={onSamples} disabled={disabled}>
            Try sample receipts
          </button>
        </div>
      </div>
      {note && <p className="mt-2 text-xs text-warn" role="status">{note}</p>}
    </div>
  );
}
