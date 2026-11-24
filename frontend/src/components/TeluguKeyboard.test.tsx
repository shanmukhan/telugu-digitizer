import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TeluguKeyboard } from "./TeluguKeyboard";
import { mapPhysicalKeyToInscript } from "../utils/teluguInscript";
import { backspaceAtCursor, insertTextAtCursor } from "../utils/teluguInput";
import { transliterateTeluguPhonetic } from "../utils/teluguTranslit";

describe("Telugu InScript & Phonetic transliteration helpers", () => {
  it("transliterates Romanized Telugu phonetics into NFC-accurate Unicode Telugu", () => {
    expect(transliterateTeluguPhonetic("telugu")).toBe("తెలుగు");
    expect(transliterateTeluguPhonetic("pustakaM")).toBe("పుస్తకం");
    expect(transliterateTeluguPhonetic("bharata")).toBe("భరత");
    expect(transliterateTeluguPhonetic("ksha")).toBe("క్ష");
    expect(transliterateTeluguPhonetic("aaMdhra")).toBe("ఆంధ్ర");
    expect(transliterateTeluguPhonetic("lakshmee")).toBe("లక్ష్మీ");
  });

  it("maps physical QWERTY keys in both Normal and Shift InScript layers", () => {
    expect(mapPhysicalKeyToInscript("k", false)).toBe("క");
    expect(mapPhysicalKeyToInscript("K", true)).toBe("ఖ");
    expect(mapPhysicalKeyToInscript("d", false)).toBe("్");
    expect(mapPhysicalKeyToInscript("D", true)).toBe("అ");
    expect(mapPhysicalKeyToInscript("<", true)).toBe("ష");
    expect(mapPhysicalKeyToInscript("/", false)).toBe("య");
  });
});

function ControlledHarness() {
  const [text, setText] = useState("తెలుగు పస్తకం");
  const [open, setOpen] = useState(true);
  const [taEl, setTaEl] = useState<HTMLTextAreaElement | null>(null);

  return (
    <div>
      <textarea
        ref={setTaEl}
        aria-label="Test Telugu line"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <TeluguKeyboard
        open={open}
        onClose={() => setOpen(false)}
        onInsertText={(inserted) => (taEl ? insertTextAtCursor(taEl, inserted) : false)}
        onBackspace={() => (taEl ? backspaceAtCursor(taEl) : false)}
        targetDescription="Test Telugu line"
      />
    </div>
  );
}

describe("TeluguKeyboard component", () => {
  it("switches between InScript Shift layer, Phonetic composer, and inserts at caret in React textarea", () => {
    render(<ControlledHarness />);

    const textarea = screen.getByLabelText("Test Telugu line") as HTMLTextAreaElement;
    textarea.focus();
    // Place cursor right after "తెలుగు ప" (index 8) so inserting "ు" yields "తెలుగు పుస్తకం"
    textarea.setSelectionRange(8, 8);

    fireEvent.click(screen.getByRole("button", { name: /Insert u sign/i }));
    expect(textarea.value).toBe("తెలుగు పుస్తకం");

    fireEvent.click(screen.getByRole("button", { name: "Backspace in active Telugu text" }));
    expect(textarea.value).toBe("తెలుగు పస్తకం");

    // Shift layer toggles K -> ఖ and D -> అ
    fireEvent.click(screen.getByRole("button", { name: "⇧ Shift" }));
    expect(screen.getByRole("button", { name: "Key K inserts ఖ" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Key D inserts అ" })).toBeInTheDocument();

    // Switch to Phonetic tab via click and verify Roman -> Telugu converter
    const phoneticTab = screen.getByRole("tab", { name: "Phonetic (Type / Tap)" });
    fireEvent.click(phoneticTab);
    expect(phoneticTab).toHaveAttribute("aria-selected", "true");

    const romanInput = screen.getByLabelText("Roman → Telugu:");
    fireEvent.change(romanInput, { target: { value: "telugu" } });
    expect(screen.getByLabelText("Converted Telugu preview")).toHaveTextContent("తెలుగు");

    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    fireEvent.click(screen.getByRole("button", { name: "Insert Telugu" }));
    expect(textarea.value).toBe("తెలుగు పస్తకంతెలుగు");
  });

  it("supports physical QWERTY InScript capture when toggled On", () => {
    const onInsert = vi.fn().mockReturnValue(true);
    render(
      <div>
        <textarea aria-label="Target box" defaultValue="" />
        <TeluguKeyboard
          open={true}
          onClose={vi.fn()}
          onInsertText={onInsert}
          onBackspace={vi.fn().mockReturnValue(true)}
          targetDescription="Target box"
        />
      </div>,
    );

    const ta = screen.getByLabelText("Target box");
    ta.focus();
    fireEvent.click(screen.getByRole("button", { name: /Physical Keys:/ }));
    fireEvent.keyDown(ta, { key: "k", shiftKey: false });
    fireEvent.keyDown(ta, { key: "e", shiftKey: false });
    expect(onInsert).toHaveBeenNthCalledWith(1, "క");
    expect(onInsert).toHaveBeenNthCalledWith(2, "ా");
  });
});
