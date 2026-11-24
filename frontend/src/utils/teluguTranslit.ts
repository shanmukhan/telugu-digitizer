interface VowelRule {
  roman: string;
  independent: string;
  matra: string;
}

interface ConsonantRule {
  roman: string;
  telugu: string;
}

const VIRAMA = "్";

const VOWEL_RULES: VowelRule[] = [
  { roman: "aa", independent: "ఆ", matra: "ా" },
  { roman: "ee", independent: "ఈ", matra: "ీ" },
  { roman: "ii", independent: "ఈ", matra: "ీ" },
  { roman: "oo", independent: "ఊ", matra: "ూ" },
  { roman: "uu", independent: "ఊ", matra: "ూ" },
  { roman: "ai", independent: "ఐ", matra: "ై" },
  { roman: "au", independent: "ఔ", matra: "ౌ" },
  { roman: "ou", independent: "ఔ", matra: "ౌ" },
  { roman: "Ru", independent: "ఋ", matra: "ృ" },
  { roman: "ae", independent: "ఏ", matra: "ే" },
  { roman: "oa", independent: "ఓ", matra: "ో" },
  { roman: "A", independent: "ఆ", matra: "ా" },
  { roman: "I", independent: "ఈ", matra: "ీ" },
  { roman: "U", independent: "ఊ", matra: "ూ" },
  { roman: "E", independent: "ఏ", matra: "ే" },
  { roman: "O", independent: "ఓ", matra: "ో" },
  { roman: "a", independent: "అ", matra: "" },
  { roman: "i", independent: "ఇ", matra: "ి" },
  { roman: "u", independent: "ఉ", matra: "ు" },
  { roman: "e", independent: "ఎ", matra: "ె" },
  { roman: "o", independent: "ఒ", matra: "ొ" },
];

const CONSONANT_RULES: ConsonantRule[] = [
  { roman: "ksh", telugu: "క్ష" },
  { roman: "chh", telugu: "ఛ" },
  { roman: "jny", telugu: "జ్ఞ" },
  { roman: "kh", telugu: "ఖ" },
  { roman: "gh", telugu: "ఘ" },
  { roman: "ng", telugu: "ఙ" },
  { roman: "ch", telugu: "చ" },
  { roman: "Ch", telugu: "ఛ" },
  { roman: "jh", telugu: "ఝ" },
  { roman: "ny", telugu: "ఞ" },
  { roman: "Th", telugu: "ఠ" },
  { roman: "Dh", telugu: "ఢ" },
  { roman: "th", telugu: "థ" },
  { roman: "dh", telugu: "ధ" },
  { roman: "ph", telugu: "ఫ" },
  { roman: "bh", telugu: "భ" },
  { roman: "sh", telugu: "శ" },
  { roman: "Sh", telugu: "ష" },
  { roman: "gn", telugu: "జ్ఞ" },
  { roman: "k", telugu: "క" },
  { roman: "g", telugu: "గ" },
  { roman: "c", telugu: "చ" },
  { roman: "j", telugu: "జ" },
  { roman: "J", telugu: "ఞ" },
  { roman: "T", telugu: "ట" },
  { roman: "D", telugu: "డ" },
  { roman: "N", telugu: "ణ" },
  { roman: "t", telugu: "త" },
  { roman: "d", telugu: "ద" },
  { roman: "n", telugu: "న" },
  { roman: "p", telugu: "ప" },
  { roman: "f", telugu: "ఫ" },
  { roman: "b", telugu: "బ" },
  { roman: "m", telugu: "మ" },
  { roman: "y", telugu: "య" },
  { roman: "r", telugu: "ర" },
  { roman: "R", telugu: "ఱ" },
  { roman: "l", telugu: "ల" },
  { roman: "L", telugu: "ళ" },
  { roman: "v", telugu: "వ" },
  { roman: "w", telugu: "వ" },
  { roman: "S", telugu: "ష" },
  { roman: "s", telugu: "స" },
  { roman: "h", telugu: "హ" },
  { roman: "G", telugu: "ఙ" },
  { roman: "x", telugu: "క్ష" },
];

/**
 * Deterministic Romanized (phonetic RTS/Lekhini-style) to Telugu Unicode transliterator.
 * Supports consonants + inherent 'a', dependent vowel signs, conjunct virama stacking,
 * 'M' (anusvara), 'H' (visarga), and multi-letter combinations like 'ksh', 'th', 'bh'.
 */
export function transliterateTeluguPhonetic(input: string): string {
  let out = "";
  let i = 0;
  let pendingConsonant: string | null = null;

  const flushConsonant = () => {
    if (pendingConsonant !== null) {
      out += pendingConsonant + VIRAMA;
      pendingConsonant = null;
    }
  };

  while (i < input.length) {
    const ch = input[i];

    if (ch === "M") {
      if (pendingConsonant !== null) {
        out += pendingConsonant + "ం";
        pendingConsonant = null;
      } else {
        out += "ం";
      }
      i += 1;
      continue;
    }

    if (ch === "H") {
      if (pendingConsonant !== null) {
        out += pendingConsonant + "ః";
        pendingConsonant = null;
      } else {
        out += "ః";
      }
      i += 1;
      continue;
    }

    if (ch === "^") {
      flushConsonant();
      i += 1;
      continue;
    }

    const slice = input.slice(i);

    const vowel = VOWEL_RULES.find((rule) => slice.startsWith(rule.roman));
    if (vowel) {
      if (pendingConsonant !== null) {
        out += pendingConsonant + vowel.matra;
        pendingConsonant = null;
      } else {
        out += vowel.independent;
      }
      i += vowel.roman.length;
      continue;
    }

    const consonant = CONSONANT_RULES.find((rule) => slice.startsWith(rule.roman));
    if (consonant) {
      flushConsonant();
      pendingConsonant = consonant.telugu;
      i += consonant.roman.length;
      continue;
    }

    flushConsonant();
    out += ch;
    i += 1;
  }

  flushConsonant();
  return out;
}

export const PHONETIC_VOWELS: Array<{ char: string; roman: string }> = [
  { char: "అ", roman: "a" },
  { char: "ఆ", roman: "aa" },
  { char: "ఇ", roman: "i" },
  { char: "ఈ", roman: "ee" },
  { char: "ఉ", roman: "u" },
  { char: "ఊ", roman: "oo" },
  { char: "ఋ", roman: "Ru" },
  { char: "ఎ", roman: "e" },
  { char: "ఏ", roman: "E" },
  { char: "ఐ", roman: "ai" },
  { char: "ఒ", roman: "o" },
  { char: "ఓ", roman: "O" },
  { char: "ఔ", roman: "au" },
  { char: "అం", roman: "aM" },
  { char: "అః", roman: "aH" },
];

export const PHONETIC_CONSONANT_GROUPS: Array<{
  title: string;
  items: Array<{ char: string; roman: string }>;
}> = [
  {
    title: "క–ఙ",
    items: [
      { char: "క", roman: "ka" },
      { char: "ఖ", roman: "kha" },
      { char: "గ", roman: "ga" },
      { char: "ఘ", roman: "gha" },
      { char: "ఙ", roman: "ng" },
    ],
  },
  {
    title: "చ–ఞ",
    items: [
      { char: "చ", roman: "ca" },
      { char: "ఛ", roman: "Cha" },
      { char: "జ", roman: "ja" },
      { char: "ఝ", roman: "jha" },
      { char: "ఞ", roman: "ny" },
    ],
  },
  {
    title: "ట–ణ",
    items: [
      { char: "ట", roman: "Ta" },
      { char: "ఠ", roman: "Tha" },
      { char: "డ", roman: "Da" },
      { char: "ఢ", roman: "Dha" },
      { char: "ణ", roman: "Na" },
    ],
  },
  {
    title: "త–న",
    items: [
      { char: "త", roman: "ta" },
      { char: "థ", roman: "tha" },
      { char: "ద", roman: "da" },
      { char: "ధ", roman: "dh" },
      { char: "న", roman: "na" },
    ],
  },
  {
    title: "ప–మ",
    items: [
      { char: "ప", roman: "pa" },
      { char: "ఫ", roman: "pha" },
      { char: "బ", roman: "ba" },
      { char: "భ", roman: "bha" },
      { char: "మ", roman: "ma" },
    ],
  },
  {
    title: "య–హ",
    items: [
      { char: "య", roman: "ya" },
      { char: "ర", roman: "ra" },
      { char: "ఱ", roman: "Ra" },
      { char: "ల", roman: "la" },
      { char: "ళ", roman: "La" },
      { char: "వ", roman: "va" },
      { char: "శ", roman: "sha" },
      { char: "ష", roman: "Sa" },
      { char: "స", roman: "sa" },
      { char: "హ", roman: "ha" },
      { char: "క్ష", roman: "ksha" },
      { char: "జ్ఞ", roman: "jna" },
    ],
  },
];
