/** Evidence highlighting for transcripts. All output is plain strings: callers render them as text nodes, never as HTML. */

export interface TextSegment {
  text: string;
  mark: boolean;
}

const KEEP = /[\p{L}\p{N}\p{M}]/u;

function normalize(text: string): { norm: string; map: number[] } {
  let norm = "";
  const map: number[] = [];
  let index = 0;
  for (const char of text) {
    if (KEEP.test(char)) {
      const lower = char.toLowerCase();
      for (const part of lower) {
        norm += part;
        map.push(index);
      }
    }
    index += char.length;
  }
  return { norm, map };
}

/**
 * Splits `text` into marked / unmarked segments for every excerpt that can be found. Matching ignores case and
 * punctuation (the server normalises excerpts), and overlapping matches are merged.
 */
export function splitByExcerpts(text: string, excerpts: ReadonlyArray<string>): TextSegment[] {
  if (!text) return [];
  const { norm, map } = normalize(text);
  const ranges: Array<[number, number]> = [];
  for (const excerpt of excerpts) {
    const needle = normalize(excerpt).norm;
    if (needle.length < 3) continue;
    let from = 0;
    while (from <= norm.length - needle.length) {
      const hit = norm.indexOf(needle, from);
      if (hit === -1) break;
      const start = map[hit]!;
      const lastChar = map[hit + needle.length - 1]!;
      const end = lastChar + (String.fromCodePoint(text.codePointAt(lastChar) ?? 32).length || 1);
      ranges.push([start, end]);
      from = hit + needle.length;
    }
  }
  if (ranges.length === 0) return [{ text, mark: false }];

  ranges.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([range[0], range[1]]);
  }

  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), mark: false });
    segments.push({ text: text.slice(start, end), mark: true });
    cursor = end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), mark: false });
  return segments;
}
