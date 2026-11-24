import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  INSCRIPT_ROWS,
  QUICK_COMBINING_SIGNS,
  mapPhysicalKeyToInscript,
} from "../utils/teluguInscript";
import { isEditableTextElement } from "../utils/teluguInput";
import {
  PHONETIC_CONSONANT_GROUPS,
  PHONETIC_VOWELS,
  transliterateTeluguPhonetic,
} from "../utils/teluguTranslit";

interface TeluguKeyboardProps {
  open: boolean;
  onClose: () => void;
  onInsertText: (text: string) => boolean;
  onBackspace: () => boolean;
  targetDescription: string | null;
}

export function TeluguKeyboard({
  open,
  onClose,
  onInsertText,
  onBackspace,
  targetDescription,
}: TeluguKeyboardProps) {
  const headingId = useId();
  const inscriptTabId = useId();
  const phoneticTabId = useId();
  const phoneticInputId = useId();

  const [mode, setMode] = useState<"inscript" | "phonetic">("inscript");
  const [shift, setShift] = useState(false);
  const [capturePhysicalKeys, setCapturePhysicalKeys] = useState(false);
  const [romanDraft, setRomanDraft] = useState("");
  const [statusMessage, setStatusMessage] = useState("");

  const inscriptTabRef = useRef<HTMLButtonElement>(null);
  const phoneticTabRef = useRef<HTMLButtonElement>(null);

  const phoneticPreview = useMemo(() => transliterateTeluguPhonetic(romanDraft), [romanDraft]);

  useEffect(() => {
    if (!open || mode !== "inscript" || !capturePhysicalKeys) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement;
      if (!isEditableTextElement(active)) return;

      const mapped = mapPhysicalKeyToInscript(event.key, event.shiftKey);
      if (mapped === null) return;

      event.preventDefault();
      onInsertText(mapped);
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, mode, capturePhysicalKeys, onInsertText]);

  if (!open) {
    return null;
  }

  function handleInsert(text: string) {
    const ok = onInsertText(text);
    if (!ok) {
      setStatusMessage("Click a Telugu text box first, then tap a key to insert.");
    } else {
      setStatusMessage("");
    }
  }

  function handleBackspace() {
    const ok = onBackspace();
    if (!ok) {
      setStatusMessage("Click a Telugu text box first.");
    } else {
      setStatusMessage("");
    }
  }

  function handleInsertPhoneticDraft(appendSpace = false) {
    if (!phoneticPreview) return;
    const text = appendSpace ? `${phoneticPreview} ` : phoneticPreview;
    const ok = onInsertText(text);
    if (ok) {
      setRomanDraft("");
      setStatusMessage(`Inserted "${phoneticPreview}".`);
    } else {
      setStatusMessage("Click a Telugu line box in the editor first to insert.");
    }
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    let nextMode: "inscript" | "phonetic" | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      nextMode = mode === "inscript" ? "phonetic" : "inscript";
    } else if (event.key === "Home") {
      nextMode = "inscript";
    } else if (event.key === "End") {
      nextMode = "phonetic";
    }
    if (!nextMode) return;
    event.preventDefault();
    setMode(nextMode);
    if (nextMode === "inscript") {
      inscriptTabRef.current?.focus();
    } else {
      phoneticTabRef.current?.focus();
    }
  }

  return (
    <section
      className="telugu-kbd-dock"
      aria-labelledby={headingId}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          onClose();
        }
      }}
    >
      <div className="telugu-kbd-header">
        <div className="toolbar-group" style={{ flexWrap: "wrap", gap: "0.65rem" }}>
          <h2 id={headingId} className="telugu-kbd-title">
            ⌨ Telugu On-Screen Keyboard
          </h2>

          <div
            role="tablist"
            aria-label="Telugu keyboard mode"
            className="kbd-tablist"
            onKeyDown={handleTabKeyDown}
          >
            <button
              ref={inscriptTabRef}
              type="button"
              role="tab"
              id={inscriptTabId}
              className="kbd-tab-btn"
              aria-selected={mode === "inscript"}
              tabIndex={mode === "inscript" ? 0 : -1}
              onClick={() => setMode("inscript")}
            >
              InScript (Standard)
            </button>
            <button
              ref={phoneticTabRef}
              type="button"
              role="tab"
              id={phoneticTabId}
              className="kbd-tab-btn"
              aria-selected={mode === "phonetic"}
              tabIndex={mode === "phonetic" ? 0 : -1}
              onClick={() => setMode("phonetic")}
            >
              Phonetic (Type / Tap)
            </button>
          </div>

          <span className="hint-text">
            {targetDescription ? `Target: ${targetDescription}` : "Click any line box or input field to type"}
          </span>
        </div>

        <div className="toolbar-group" role="group" aria-label="Common keyboard actions">
          {mode === "inscript" && (
            <button
              type="button"
              className="btn-compact"
              aria-pressed={capturePhysicalKeys}
              title="Map your physical laptop QWERTY keys directly to Telugu InScript when editing text"
              onClick={() => setCapturePhysicalKeys((v) => !v)}
            >
              Physical Keys: {capturePhysicalKeys ? "On" : "Off"}
            </button>
          )}
          <button
            type="button"
            className="btn-compact"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => handleInsert(" ")}
          >
            Space
          </button>
          <button
            type="button"
            className="btn-compact"
            aria-label="Backspace in active Telugu text"
            onMouseDown={(e) => e.preventDefault()}
            onClick={handleBackspace}
          >
            ⌫ Backspace
          </button>
          <button
            type="button"
            className="btn-compact"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => handleInsert("\n")}
          >
            ↵ New Line
          </button>
          <button type="button" className="btn-compact" onClick={onClose}>
            Hide Keyboard
          </button>
        </div>
      </div>

      {statusMessage && (
        <p className="hint-text" role="status" aria-live="polite" style={{ margin: "0 0 0.4rem" }}>
          {statusMessage}
        </p>
      )}

      <div role="tabpanel" aria-labelledby={inscriptTabId} hidden={mode !== "inscript"}>
        <div className="kbd-body-wrapper">
          <div className="kbd-signs-strip" role="group" aria-label="Telugu vowel signs and modifiers">
            <span className="hint-text" style={{ fontWeight: 600 }}>
              Signs:
            </span>
            {QUICK_COMBINING_SIGNS.map((sign) => (
              <button
                key={sign.char}
                type="button"
                className="kbd-key kbd-key-sign"
                lang="te"
                title={sign.hint}
                aria-label={`Insert ${sign.hint} ${sign.char}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleInsert(sign.char)}
              >
                <span className="kbd-primary-glyph">{sign.char}</span>
              </button>
            ))}
          </div>

          <div className="inscript-grid" role="group" aria-label="Telugu InScript keyboard rows">
            {INSCRIPT_ROWS.map((row, rowIdx) => (
              <div key={rowIdx} className="inscript-row">
                {rowIdx === 3 && (
                  <button
                    type="button"
                    className={`kbd-key kbd-key-modifier ${shift ? "active" : ""}`.trim()}
                    aria-pressed={shift}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => setShift((s) => !s)}
                  >
                    ⇧ Shift
                  </button>
                )}
                {row.map((keyDef) => {
                  const primaryChar = shift ? keyDef.shift : keyDef.normal;
                  const secondaryChar = shift ? keyDef.normal : keyDef.shift;
                  return (
                    <button
                      key={keyDef.codeKey}
                      type="button"
                      className="kbd-key"
                      aria-label={`Key ${keyDef.label} inserts ${primaryChar}`}
                      title={`QWERTY ${keyDef.label}: ${keyDef.normal} (Shift: ${keyDef.shift})`}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => handleInsert(primaryChar)}
                    >
                      <span className="kbd-qwerty-hint">{keyDef.label}</span>
                      <span className="kbd-primary-glyph" lang="te">
                        {primaryChar}
                      </span>
                      {secondaryChar !== primaryChar && (
                        <span className="kbd-secondary-glyph" lang="te">
                          {secondaryChar}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div role="tabpanel" aria-labelledby={phoneticTabId} hidden={mode !== "phonetic"}>
        <div className="kbd-body-wrapper">
          <div className="phonetic-composer-row">
            <label htmlFor={phoneticInputId} className="hint-text" style={{ fontWeight: 600 }}>
              Roman → Telugu:
            </label>
            <input
              id={phoneticInputId}
              type="text"
              data-telugu-kbd-ignore="true"
              className="phonetic-roman-input"
              placeholder='Type English letters (e.g. "telugu", "pustakaM", "ksha")'
              value={romanDraft}
              onChange={(e) => setRomanDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && phoneticPreview) {
                  e.preventDefault();
                  if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) {
                    return;
                  }
                  handleInsertPhoneticDraft(false);
                }
              }}
            />
            <div className="phonetic-preview-box" lang="te" aria-label="Converted Telugu preview">
              {phoneticPreview || "తెలుగు"}
            </div>
            <button
              type="button"
              className="primary btn-compact"
              disabled={!phoneticPreview}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleInsertPhoneticDraft(false)}
            >
              Insert Telugu
            </button>
            {romanDraft && (
              <button
                type="button"
                className="btn-compact"
                onClick={() => setRomanDraft("")}
              >
                Clear
              </button>
            )}
          </div>

          <div className="phonetic-grids">
            <div className="phonetic-section">
              <span className="hint-text" style={{ fontWeight: 600 }}>
                Vowels (అచ్చులు):
              </span>
              <div className="phonetic-chip-wrap">
                {PHONETIC_VOWELS.map((item) => (
                  <button
                    key={item.char}
                    type="button"
                    className="kbd-key kbd-key-phonetic"
                    aria-label={`Insert ${item.char} (${item.roman})`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleInsert(item.char)}
                  >
                    <span className="kbd-primary-glyph" lang="te">
                      {item.char}
                    </span>
                    <span className="kbd-roman-hint">{item.roman}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="phonetic-section">
              <span className="hint-text" style={{ fontWeight: 600 }}>
                Matras / Halant (గుణింతపు గుర్తులు):
              </span>
              <div className="phonetic-chip-wrap">
                {QUICK_COMBINING_SIGNS.map((sign) => (
                  <button
                    key={sign.char}
                    type="button"
                    className="kbd-key kbd-key-sign"
                    title={sign.hint}
                    aria-label={`Insert ${sign.hint} ${sign.char}`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => handleInsert(sign.char)}
                  >
                    <span className="kbd-primary-glyph" lang="te">
                      {sign.char}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="phonetic-consonant-groups">
              {PHONETIC_CONSONANT_GROUPS.map((group) => (
                <div key={group.title} className="phonetic-varga-group">
                  <span className="hint-text" style={{ fontWeight: 600, minInlineSize: "2.4rem" }}>
                    {group.title}
                  </span>
                  <div className="phonetic-chip-wrap">
                    {group.items.map((item) => (
                      <button
                        key={item.char}
                        type="button"
                        className="kbd-key kbd-key-phonetic"
                        aria-label={`Insert ${item.char} (${item.roman})`}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => handleInsert(item.char)}
                      >
                        <span className="kbd-primary-glyph" lang="te">
                          {item.char}
                        </span>
                        <span className="kbd-roman-hint">{item.roman}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
