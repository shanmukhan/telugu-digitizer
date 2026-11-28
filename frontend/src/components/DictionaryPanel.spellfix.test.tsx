import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { DictionaryPanel } from "./DictionaryPanel";

describe("DictionaryPanel exact token_index spell-fix replacement", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("replaces only the flagged occurrence when duplicate words appear earlier in the text", async () => {
    vi.spyOn(client, "getDictionaryStats").mockResolvedValue({
      available: true,
      has_definitions_db: true,
      total_words: 195000,
      words_with_definitions: 60000,
      total_definitions: 90000,
      custom_words_count: 0,
      source_definition_counts: {},
      built_at: null,
    });
    vi.spyOn(client, "listCustomDictionaryWords").mockResolvedValue([]);
    vi.spyOn(client, "checkTeluguText").mockResolvedValue({
      total_telugu_words: 3,
      known_words_count: 2,
      unknown_words_count: 1,
      issues: [
        {
          token: "పన",
          token_index: 2,
          best_replacement: "పని",
          confidence: 0.96,
          reason: "OCR substitution",
          suggestions: ["పని"],
        },
      ],
    });

    const onBanner = vi.fn();
    render(<DictionaryPanel onStatusBanner={onBanner} />);

    fireEvent.click(screen.getByRole("tab", { name: /Check Telugu Text/i }));
    const textarea = screen.getByLabelText(/Paste or type Telugu text/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "పన పనిచేయడం పన" } });
    fireEvent.click(screen.getByRole("button", { name: /Check Spelling/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /పని/ })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: /పని/ }));

    expect(textarea.value).toBe("పన పనిచేయడం పని");
  });
});
