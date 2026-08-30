---
name: ContextRail
description: The Evidence Signal Box — an operational control plane for governed multi-agent work.
version: 1.0.0
updated: 2026-08-26
---

# 1. Design direction

## North Star: The Evidence Signal Box

ContextRail should feel like a calm operations room built around one moving object: the Context Capsule. The interface is dark, precise, and evidentiary. It reveals why the rail is clear, held, or stopped without pretending that density is sophistication.

The product is not a generic dashboard. Each screen answers one operational question: what was requested, what evidence governs it, who owns the next decision, what is blocked, and what was verified.

# 2. Foundations

## Color

| Token | Value | Use |
|---|---:|---|
| `ink` | `#07090e` | Page background |
| `panel` | `#0d111a` | Primary surface |
| `panel-2` | `#121826` | Raised or nested surface |
| `panel-3` | `#18202f` | Interactive hover surface |
| `line` | `#1c2434` | Quiet dividers |
| `line-strong` | `#2b3548` | Interactive boundaries |
| `text` | `#e9edf6` | Primary text |
| `muted` | `#9aa4b8` | Supporting text |
| `dim` | `#7e88a0` | Quiet metadata and micro-labels |
| `rail` | `#6e8cff` | Navigation, focus, active stage |
| `clear` | `#3ddc97` | Allowed, complete, verified |
| `caution` | `#f5a623` | Held, stale, approval required |
| `stop` | `#ff5a5f` | Denied, failed, blocked |

Green, amber, and red are reserved for state. They are never decorative — a figure is
toned only when an actual state condition drives it, never by sentiment.

Every step of the text ramp clears WCAG AA (4.5:1) on all four surface tokens, `panel-3`
included. The previous `dim` (`#5a6377`) measured 2.71:1 there and failed across roughly
200 measured instances, including the run console's tab bar.

## Typography

- Display: Archivo, 600–700, compact headings.
- Body: Inter, 400–600, minimum 14px on narrow screens and 12px only for dense desktop support text.
- Data: JetBrains Mono, used for identifiers, tools, timestamps, and concise labels—not paragraphs.

## Spacing and shape

- Base unit: 4px; common gaps: 8, 12, 16, 24, 32.
- Radius: 6px controls, 10px panels, fully rounded only for status lamps and compact badges.
- Elevation: tonal surfaces and borders. Shadows are limited to dialogs and overlays.
- Touch target: 44×44px minimum on narrow screens.

# 3. Layout system

- A persistent 60px navigation rail anchors the product.
- Primary content is capped between 980px and 1180px depending on task density.
- The desktop command center uses a fluid main column and a 320px operational sidebar.
- Below the large breakpoint, all content becomes a single reading order.
- Section headings stack their metadata below the title on narrow screens.
- Dense rows become two-line records rather than clipping or horizontal scrolling.

# 4. Component language

- **Signal lamp:** 6–8px semantic dot paired with a text label. Color is never the only status cue.
- **Stage rail:** vertical sequence with explicit stage names, state, and explanatory note.
- **Context Capsule:** bordered evidence surface with a readable mode and an optional raw structured mode.
- **Policy verdict:** full bordered panel containing applicability, reason, and a separate citation well.
- **Action row:** owner, tool, dependencies, risk, result, and post-condition; denied actions remain visible and struck through.
- **Approval record:** named owner, policy ID, evidence-backed reason, typed decision note, timestamp.
- **Buttons:** one primary action per surface; secondary actions are outlined or quiet. Mobile height is 44px.
- **Inputs:** persistent labels, visible focus, clear invalid states, no placeholder-only instructions.

# 5. Content rules

- Lead with the operational outcome, not platform vocabulary.
- Say “denied,” “held,” “verified,” or “unverified”; avoid vague success language.
- Name the subject and the policy whenever space permits.
- Explain what a metric means; never rely on a large number without context.
- Use sentence case. Reserve uppercase monospace for short control-plane labels.
- Do not use authoring-tool branding, generated-by marks, decorative gradients, side-stripe cards, repeated hero metrics, or vague security theatre.

# 6. Accessibility and quality bar

- Target WCAG 2.2 AA contrast and keyboard operation.
- Preserve visible focus on every interactive element.
- Honor reduced-motion preferences; live lamps may stop pulsing without losing their text state.
- Never encode state by color alone.
- No horizontal page overflow at 390px.
- Truncation is acceptable only when the full value is available through navigation or accessible text.
- Every final visual review covers 1440×900 and 390×844 screenshots for the Command Center, New Request, Approval Center, and Skills & Tools.
