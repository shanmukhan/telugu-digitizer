import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as apiClient from "../api/client";
import { DictionaryPanel } from "./DictionaryPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getDictionaryStats: vi.fn(),
    searchDictionary: vi.fn(),
    getDictionaryWord: vi.fn(),
    checkTeluguText: vi.fn(),
    listCustomDictionaryWords: vi.fn(),
    createCustomDictionaryWord: vi.fn(),
    deleteCustomDictionaryWord: vi.fn(),
  };
});

describe("DictionaryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.getDictionaryStats).mockResolvedValue({
      available: true,
      has_definitions_db: true,
      total_words: 195505,
      words_with_definitions: 89394,
      total_definitions: 123776,
      custom_words_count: 1,
      source_definition_counts: { cp_brown: 19682, wiktionary_te: 79266, janapada: 24828 },
      built_at: "2026-11-28T00:00:00Z",
    });
    vi.mocked(apiClient.listCustomDictionaryWords).mockResolvedValue([
      {
        word_id: "cw-1",
        language_code: "te",
        word: "లహరిప్రబంధము",
        translit: "lahari",
        meaning_en: "Custom literary term",
        meaning_te: null,
        notes: null,
        created_at: "2026-11-28T00:00:00Z",
        updated_at: "2026-11-28T00:00:00Z",
      },
    ]);
    vi.mocked(apiClient.searchDictionary).mockResolvedValue({
      query: "పుస్తకము",
      detected_mode: "telugu",
      exact_match: true,
      items: [
        {
          word: "పుస్తకము",
          weight: 225,
          sources: ["C.P. Brown", "Wiktionary"],
          translit: "pustakamu",
          has_definition: true,
          is_custom: false,
          custom_word_id: null,
          definitions: [{ source: "cp_brown", lang: "en", definition: "n. A book, a volume." }],
        },
      ],
      did_you_mean: [],
    });
    vi.mocked(apiClient.getDictionaryWord).mockResolvedValue({
      word: "పుస్తకము",
      found: true,
      is_valid_word: true,
      weight: 225,
      sources: ["C.P. Brown", "Wiktionary"],
      translit: "pustakamu",
      is_custom: false,
      custom_word_id: null,
      definitions: [{ source: "cp_brown", lang: "en", definition: "n. A book, a volume." }],
      did_you_mean: [],
    });
    vi.mocked(apiClient.checkTeluguText).mockResolvedValue({
      total_telugu_words: 2,
      known_words_count: 1,
      unknown_words_count: 1,
      issues: [
        {
          token: "పస్తకం",
          token_index: 1,
          best_replacement: "పుస్తకం",
          confidence: 0.9,
          reason: "Telugu dictionary + OCR similarity match",
          suggestions: ["పుస్తకం"],
        },
      ],
    });
    vi.mocked(apiClient.createCustomDictionaryWord).mockResolvedValue({
      word_id: "cw-2",
      language_code: "te",
      word: "ఆముక్త",
      translit: "amukta",
      meaning_en: "Worn and offered",
      meaning_te: null,
      notes: null,
      created_at: "2026-11-28T00:00:00Z",
      updated_at: "2026-11-28T00:00:00Z",
    });
  });

  it("renders dictionary stats, searches words with definitions, checks Telugu text, and adds custom words", async () => {
    const onStatusBanner = vi.fn();
    render(<DictionaryPanel onStatusBanner={onStatusBanner} />);

    await waitFor(() => {
      expect(screen.getByText(/195,505 Telugu words/)).toBeInTheDocument();
    });

    const input = screen.getByLabelText(/Search Telugu word/i);
    fireEvent.change(input, { target: { value: "పుస్తకము" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(apiClient.searchDictionary).toHaveBeenCalledWith("పుస్తకము", {
        mode: "auto",
        limit: 30,
      });
      expect(screen.getByText("C.P. Brown (Classical)")).toBeInTheDocument();
      expect(screen.getAllByText(/n\. A book, a volume\./).length).toBeGreaterThanOrEqual(1);
    });

    // Switch to Check Telugu Text
    fireEvent.click(screen.getByRole("tab", { name: "✓ Check Telugu Text" }));
    const area = screen.getByLabelText(/Paste or type Telugu text/i) as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "తెలుగు పస్తకం" } });
    fireEvent.click(screen.getByRole("button", { name: "✓ Check Spelling" }));

    await waitFor(() => {
      expect(screen.getByText("Flagged: 1")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /పుస్తకం/ }));
    expect(area.value).toBe("తెలుగు పుస్తకం");

    // Switch to Custom Words and add one
    fireEvent.click(screen.getByRole("tab", { name: /Custom Words/ }));
    fireEvent.change(screen.getByLabelText("Telugu Word *"), { target: { value: "ఆముక్త" } });
    fireEvent.change(screen.getByLabelText("English Meaning (optional)"), {
      target: { value: "Worn and offered" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Custom Word" }));

    await waitFor(() => {
      expect(apiClient.createCustomDictionaryWord).toHaveBeenCalledWith(
        expect.objectContaining({
          word: "ఆముక్త",
          meaning_en: "Worn and offered",
        }),
      );
      expect(onStatusBanner).toHaveBeenCalledWith("success", expect.stringContaining("ఆముక్త"));
    });
  });
});
