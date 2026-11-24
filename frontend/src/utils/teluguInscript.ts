export interface InscriptKeyDef {
  /** Physical QWERTY key label (unshifted) */
  codeKey: string;
  /** Display key cap hint when unshifted */
  label: string;
  /** Output character in Normal state */
  normal: string;
  /** Output character in Shift state */
  shift: string;
}

/**
 * BIS / CDAC standard Telugu InScript keymap rows.
 * Dependent vowel signs (matras) & virama sit on Normal keys on the left hand;
 * independent vowels sit on the matching Shift keys.
 */
export const INSCRIPT_ROWS: InscriptKeyDef[][] = [
  [
    { codeKey: "`", label: "`", normal: "ొ", shift: "ఒ" },
    { codeKey: "1", label: "1", normal: "1", shift: "౧" },
    { codeKey: "2", label: "2", normal: "2", shift: "౨" },
    { codeKey: "3", label: "3", normal: "3", shift: "౩" },
    { codeKey: "4", label: "4", normal: "4", shift: "౪" },
    { codeKey: "5", label: "5", normal: "5", shift: "జ్ఞ" },
    { codeKey: "6", label: "6", normal: "6", shift: "త్ర" },
    { codeKey: "7", label: "7", normal: "7", shift: "క్ష" },
    { codeKey: "8", label: "8", normal: "8", shift: "శ్ర" },
    { codeKey: "9", label: "9", normal: "9", shift: "(" },
    { codeKey: "0", label: "0", normal: "0", shift: ")" },
    { codeKey: "-", label: "-", normal: "-", shift: "ః" },
    { codeKey: "=", label: "=", normal: "ృ", shift: "ఋ" },
  ],
  [
    { codeKey: "q", label: "Q", normal: "ౌ", shift: "ఔ" },
    { codeKey: "w", label: "W", normal: "ై", shift: "ఐ" },
    { codeKey: "e", label: "E", normal: "ా", shift: "ఆ" },
    { codeKey: "r", label: "R", normal: "ీ", shift: "ఈ" },
    { codeKey: "t", label: "T", normal: "ూ", shift: "ఊ" },
    { codeKey: "y", label: "Y", normal: "బ", shift: "భ" },
    { codeKey: "u", label: "U", normal: "హ", shift: "ఙ" },
    { codeKey: "i", label: "I", normal: "గ", shift: "ఘ" },
    { codeKey: "o", label: "O", normal: "ద", shift: "ధ" },
    { codeKey: "p", label: "P", normal: "జ", shift: "ఝ" },
    { codeKey: "[", label: "[", normal: "డ", shift: "ఢ" },
    { codeKey: "]", label: "]", normal: "ఞ", shift: "ఞ" },
  ],
  [
    { codeKey: "a", label: "A", normal: "ో", shift: "ఓ" },
    { codeKey: "s", label: "S", normal: "ే", shift: "ఏ" },
    { codeKey: "d", label: "D", normal: "్", shift: "అ" },
    { codeKey: "f", label: "F", normal: "ి", shift: "ఇ" },
    { codeKey: "g", label: "G", normal: "ు", shift: "ఉ" },
    { codeKey: "h", label: "H", normal: "ప", shift: "ఫ" },
    { codeKey: "j", label: "J", normal: "ర", shift: "ఱ" },
    { codeKey: "k", label: "K", normal: "క", shift: "ఖ" },
    { codeKey: "l", label: "L", normal: "త", shift: "థ" },
    { codeKey: ";", label: ";", normal: "చ", shift: "ఛ" },
    { codeKey: "'", label: "'", normal: "ట", shift: "ఠ" },
  ],
  [
    { codeKey: "z", label: "Z", normal: "ె", shift: "ఎ" },
    { codeKey: "x", label: "X", normal: "ం", shift: "ఁ" },
    { codeKey: "c", label: "C", normal: "మ", shift: "ణ" },
    { codeKey: "v", label: "V", normal: "న", shift: "న" },
    { codeKey: "b", label: "B", normal: "వ", shift: "ౄ" },
    { codeKey: "n", label: "N", normal: "ల", shift: "ళ" },
    { codeKey: "m", label: "M", normal: "స", shift: "శ" },
    { codeKey: ",", label: ",", normal: ",", shift: "ష" },
    { codeKey: ".", label: ".", normal: ".", shift: "।" },
    { codeKey: "/", label: "/", normal: "య", shift: "?" },
  ],
];

const SHIFTED_MAP = new Map<string, string>();
const NORMAL_MAP = new Map<string, string>();

const SHIFTED_ALIASES: Record<string, string> = {
  "`": "~",
  "1": "!",
  "2": "@",
  "3": "#",
  "4": "$",
  "5": "%",
  "6": "^",
  "7": "&",
  "8": "*",
  "9": "(",
  "0": ")",
  "-": "_",
  "=": "+",
  "[": "{",
  "]": "}",
  ";": ":",
  "'": '"',
  ",": "<",
  ".": ">",
  "/": "?",
};

for (const row of INSCRIPT_ROWS) {
  for (const keyDef of row) {
    NORMAL_MAP.set(keyDef.codeKey, keyDef.normal);
    if (/^[a-z]$/.test(keyDef.codeKey)) {
      SHIFTED_MAP.set(keyDef.codeKey.toUpperCase(), keyDef.shift);
    } else if (SHIFTED_ALIASES[keyDef.codeKey]) {
      SHIFTED_MAP.set(SHIFTED_ALIASES[keyDef.codeKey], keyDef.shift);
    }
  }
}

export function mapPhysicalKeyToInscript(key: string, shiftKey: boolean): string | null {
  if (shiftKey) {
    return SHIFTED_MAP.get(key) ?? SHIFTED_MAP.get(key.toUpperCase()) ?? null;
  }
  return NORMAL_MAP.get(key.toLowerCase()) ?? NORMAL_MAP.get(key) ?? null;
}

export const QUICK_COMBINING_SIGNS: Array<{ char: string; hint: string }> = [
  { char: "్", hint: "Virama (Halant)" },
  { char: "ా", hint: "aa sign" },
  { char: "ి", hint: "i sign" },
  { char: "ీ", hint: "ee sign" },
  { char: "ు", hint: "u sign" },
  { char: "ూ", hint: "oo sign" },
  { char: "ృ", hint: "ru sign" },
  { char: "ె", hint: "e sign" },
  { char: "ే", hint: "E sign" },
  { char: "ై", hint: "ai sign" },
  { char: "ొ", hint: "o sign" },
  { char: "ో", hint: "O sign" },
  { char: "ౌ", hint: "au sign" },
  { char: "ం", hint: "Anusvara" },
  { char: "ః", hint: "Visarga" },
  { char: "ఁ", hint: "Candrabindu" },
];
