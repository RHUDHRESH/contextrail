import { CORPUS, SYNONYMS, type CorpusDoc } from "./data/corpus";
import type { Evidence, SystemId } from "./types";

/* ------------------------------------------------------------------ *
 * Lightweight lexical retrieval: BM25-style term scoring, synonym
 * expansion, tag boosting, source authority, and a freshness check.
 * Deliberately dependency-free — a vector store can replace `score`
 * without touching the Evidence contract the rest of the rail consumes.
 * ------------------------------------------------------------------ */

const STOP = new Set([
  "a", "an", "and", "the", "for", "to", "of", "in", "on", "is", "are", "her", "his", "their",
  "she", "he", "they", "it", "with", "we", "our", "needs", "need", "please", "want", "wants",
  "give", "set", "up", "everything", "start", "starts", "can", "should", "be", "has", "have",
]);

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 2 && !STOP.has(t));
}

function expand(terms: string[]): string[] {
  const out = new Set(terms);
  for (const t of terms) {
    for (const [root, syns] of Object.entries(SYNONYMS)) {
      if (t.startsWith(root) || syns.some((s) => s.includes(t) || t.includes(s.split(" ")[0]))) {
        out.add(root);
        syns.forEach((s) => s.split(" ").forEach((w) => w.length > 2 && out.add(w)));
      }
    }
  }
  return [...out];
}

const K1 = 1.4;
const B = 0.72;

function buildIndex(docs: CorpusDoc[]) {
  const df = new Map<string, number>();
  const lens = new Map<string, number>();
  const tf = new Map<string, Map<string, number>>();
  for (const d of docs) {
    const toks = tokenize(`${d.title} ${d.body} ${d.tags.join(" ")}`);
    lens.set(d.id, toks.length);
    const counts = new Map<string, number>();
    for (const t of toks) counts.set(t, (counts.get(t) ?? 0) + 1);
    tf.set(d.id, counts);
    for (const t of counts.keys()) df.set(t, (df.get(t) ?? 0) + 1);
  }
  const avgLen = [...lens.values()].reduce((a, b) => a + b, 0) / Math.max(1, lens.size);
  return { df, lens, tf, avgLen, n: docs.length };
}

const INDEX = buildIndex(CORPUS);

function bm25(doc: CorpusDoc, terms: string[]): number {
  const counts = INDEX.tf.get(doc.id)!;
  const len = INDEX.lens.get(doc.id)!;
  let score = 0;
  for (const t of terms) {
    const f = counts.get(t);
    if (!f) continue;
    const idf = Math.log(1 + (INDEX.n - (INDEX.df.get(t) ?? 0) + 0.5) / ((INDEX.df.get(t) ?? 0) + 0.5));
    score += idf * ((f * (K1 + 1)) / (f + K1 * (1 - B + B * (len / INDEX.avgLen))));
  }
  return score;
}

function daysSince(iso: string, now: Date): number {
  return (now.getTime() - new Date(iso).getTime()) / 86_400_000;
}

export type RetrievalOptions = {
  sources?: SystemId[];
  limit?: number;
  minConfidence?: number;
  /** Extra terms the caller already knows are relevant (intent keywords, entity names). */
  boostTerms?: string[];
  now?: Date;
};

export function searchCorpus(query: string, opts: RetrievalOptions = {}): Evidence[] {
  const now = opts.now ?? new Date("2026-08-25T09:00:00Z");
  const limit = opts.limit ?? 8;
  const base = tokenize(`${query} ${(opts.boostTerms ?? []).join(" ")}`);
  const terms = expand(base);
  const pool = opts.sources?.length ? CORPUS.filter((d) => opts.sources!.includes(d.system)) : CORPUS;

  const raw = pool.map((doc) => {
    const lexical = bm25(doc, terms);
    const tagHits = doc.tags.filter((t) => terms.some((q) => t.includes(q) || q.includes(t))).length;
    const titleHits = tokenize(doc.title).filter((t) => base.includes(t)).length;
    return { doc, raw: lexical + tagHits * 1.15 + titleHits * 1.6 };
  });

  const max = Math.max(...raw.map((r) => r.raw), 1);

  return raw
    .filter((r) => r.raw > 0.6)
    .map(({ doc, raw: rawScore }) => {
      const relevance = rawScore / max;
      // Authority pulls a weakly-matched but canonical source up, and caps
      // a strongly-matched but low-trust one (a Slack thread) below it.
      const confidence = Math.min(1, Number((relevance * 0.68 + doc.authority * 0.32).toFixed(2)));
      const age = daysSince(doc.updatedAt, now);
      return {
        id: doc.id,
        system: doc.system,
        kind: doc.kind,
        title: doc.title,
        excerpt: pickExcerpt(doc, terms),
        data: doc.data as Record<string, unknown> | undefined,
        confidence,
        lastVerifiedAt: doc.updatedAt,
        stale: age > doc.freshnessBudgetDays,
        url: doc.url,
      } satisfies Evidence;
    })
    .filter((e) => e.confidence >= (opts.minConfidence ?? 0.35))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, limit);
}

/** Return the sentence that best justifies the match, not the first sentence. */
function pickExcerpt(doc: CorpusDoc, terms: string[]): string {
  const sentences = doc.body
    .split(/\n+|(?<=\.)\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 24);
  if (!sentences.length) return doc.body.slice(0, 220);
  let best = sentences[0];
  let bestScore = -1;
  for (const s of sentences) {
    const toks = tokenize(s);
    const score = toks.filter((t) => terms.includes(t)).length / Math.sqrt(toks.length || 1);
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }
  return best.length > 300 ? `${best.slice(0, 297)}…` : best;
}

export function getDoc(id: string): CorpusDoc | undefined {
  return CORPUS.find((d) => d.id === id);
}

/**
 * Fetch a record by id rather than by lexical match.
 *
 * Search finds documents; the *subject* of a workflow is looked up. Relying on
 * the query to surface the employee or account record is how a paraphrased
 * request ends up governed by the wrong policy set — so intents declare the
 * anchor records they always need, and those are pinned into the evidence.
 */
export function fetchAnchor(id: string, now = new Date("2026-08-25T09:00:00Z")): Evidence | undefined {
  const doc = getDoc(id);
  if (!doc) return undefined;
  const age = daysSince(doc.updatedAt, now);
  return {
    id: doc.id,
    system: doc.system,
    kind: doc.kind,
    title: doc.title,
    excerpt: doc.body.split(/\n+/).map((l) => l.trim()).find((l) => l.length > 24) ?? doc.body.slice(0, 220),
    data: doc.data as Record<string, unknown> | undefined,
    // Anchors are fetched by identity, so relevance is not in question —
    // confidence reflects the source's own authority.
    confidence: Math.min(1, Number((0.62 + doc.authority * 0.38).toFixed(2))),
    lastVerifiedAt: doc.updatedAt,
    stale: age > doc.freshnessBudgetDays,
    url: doc.url,
  } satisfies Evidence;
}

/**
 * The sentence in a source document that best supports a *specific* claim.
 *
 * Evidence carries one excerpt chosen for the user's query, which is the wrong
 * quote when seven different policies all cite the same document. Each policy
 * asks for its own sentence.
 */
export function excerptFor(docId: string, terms: string[]): string | undefined {
  const doc = getDoc(docId);
  if (!doc) return undefined;
  return pickExcerpt(doc, expand(tokenize(terms.join(" "))));
}
