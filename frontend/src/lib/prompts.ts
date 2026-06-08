// Rotating, playful calls-to-action for the card deck. We never show the
// mechanical "pull thread" — each card gets an inviting nudge instead, chosen
// deterministically from its id so the copy is varied across cards but stable
// across re-renders (no flicker). The button keeps a fixed aria-label
// ("Explore further" / "Answer this") for accessibility + tests.

const CONCEPT_CTAS = [
  "Explore this further",
  "Want to know more?",
  "Take me deeper →",
  "Tell me the story",
  "Why does this matter?",
  "Unpack this",
  "Down the rabbit hole →",
  "Show me something surprising",
  "Connect the dots",
  "What's the catch?",
];

const QUESTION_CTAS = [
  "Let's answer this",
  "Figure this out",
  "Crack it open",
  "Chase this down →",
];

// Lightweight idle nudges shown when the deck is empty, to spark a first subject.
export const IDLE_NUDGES = [
  "What are you curious about?",
  "Name anything — I'll build it out.",
  "Pick a person, an idea, a question…",
  "Where should we start?",
];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** Stable, varied CTA copy for a card. */
export function ctaLabel(kind: string | undefined, id: string): string {
  const pool = kind === "question" ? QUESTION_CTAS : CONCEPT_CTAS;
  return pool[hash(id) % pool.length];
}

/** Stable accessible name (visible copy rotates; this does not). */
export function ctaAria(kind: string | undefined): string {
  return kind === "question" ? "Answer this" : "Explore further";
}

/** A stable idle nudge for an empty deck. */
export function idleNudge(seed: string): string {
  return IDLE_NUDGES[hash(seed) % IDLE_NUDGES.length];
}
