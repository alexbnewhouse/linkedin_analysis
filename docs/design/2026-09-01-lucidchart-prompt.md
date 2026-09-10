# Prompt for the Lucidchart AI agent

Paste everything inside the rule below into Lucid's AI diagram generator. It is written to
be self-contained — the agent has none of our context, so every label is given verbatim and
every connection is stated explicitly. The one thing that reliably goes wrong with these
agents is paraphrasing, so the prompt says not to.

If the first pass comes back with the bands stacked wrongly, the fix that usually works is
to re-run with "build it band by band, top to bottom, and place every shape in a band before
drawing any connectors."

---

Build a top-to-bottom flowchart on a portrait canvas titled **The discovery flow**.

It maps how a humanities undergraduate moves through a career-exploration website, from "I
have no idea what I can do with this degree" to a specific job, a named route into it, and
one thing they can do this semester.

**Use my label text exactly as written. Do not paraphrase, shorten, or re-word any label. Do
not add shapes, steps, decision diamonds, start/end terminators, or icons that I have not
listed.**

## Layout

Five horizontal bands, stacked top to bottom, each with a small left-aligned band heading in
uppercase letter-spaced type. Content width is uniform across all bands so the shapes align
on a shared grid. Leave a 200px empty margin down the right-hand side for a return connector.

## Band 1 — heading: `1 — THREE WAYS IN`

Three equal rounded rectangles side by side. Each has a bold first line and lighter
supporting lines beneath.

1. **What I studied** / Your field, or the one you are thinking about
2. **What I like doing** / Eleven kinds of work, described in the first person
3. **A job I'm curious about** / Any of thirteen thousand real job titles

All three connect down and inward to a single merge point, then one arrow continues down into
Band 2. Label that arrow: `each one sets a starting point, a destination, or both`

## Band 2 — heading: `2 — ONE EXPLORER`

First, one full-width rounded rectangle, filled in the accent green:

> **Two poles: where you are coming from, and where you are headed**
> Set either one, both, or neither. What you see follows from what you have picked — there is nothing else to learn.

One arrow straight down from it, splitting to four equal rounded rectangles side by side.
Each has a small uppercase condition line at the top, a bold mode name, and supporting text.

| Condition line | Bold name | Supporting text | Extra |
|---|---|---|---|
| `NEITHER SET` | The field | Every destination at once. Nothing ranked, nothing drawn as the answer. | — |
| `STARTING POINT SET` | The forward fan | Where people who started here were, ten years later. | green uppercase footer: `WHERE CAN I GO` |
| `DESTINATION SET` | Who is already there | People doing this work came from these places, and studied these things. | — |
| `BOTH SET` | The corridor | The route between them: who took it, what they carried, how long it took. | green uppercase footer: `HOW DO I GET THERE` |

Give the two boxes with green footers a green outline; give the other two a plain grey
outline.

Beneath the four, one full-width rectangle with a **dashed** border and no fill:

> **Any of the four can be re-sorted**
> most common first · most distinctive first · rarest describable first
> The third order is the one that surprises people: thirteen thousand specific jobs, each one named and counted.

One arrow down into Band 3, labelled: `open any destination`

## Band 3 — heading: `3 — INSIDE ONE KIND OF WORK · THE ORDER IS THE ARGUMENT`

Five equal rounded rectangles side by side, in this left-to-right order. Each carries a small
uppercase sequence word, a bold name, and supporting text.

1. `FIRST` — **What this work involves** / In the words of people who do it
2. `THEN` — **Ways in** / Entry roles, entry employers, and the first job people held
3. `THEN` — **What they studied** / Field, level, and kind of institution
4. `THEN` — **What they carried** / The credentials that show up most often
5. `LAST` — **Where it happened** / Employers, and where in the country

Give box 2 (**Ways in**) the green fill and green outline; leave the other four plain. Do not
draw connectors between these five — the sequence words carry the order.

One arrow down into Band 4.

## Band 4 — heading: `4 — NARROW TO PEOPLE LIKE YOU`

One full-width container rectangle with the bold heading inside it:

> **Add your own field of study, and watch the count**

Inside that container, three small rounded rectangles in a row, connected left to right by two
short arrows:

1. **Your field, your route** / the most specific answer
2. **Too few to describe?** / the map widens one step
3. **And says so, in words** / never a blank screen

To the right of those three, inside the same container, plain text with no box:

> The count is on the screen at every step, not in a footnote.

One arrow down into Band 5.

## Band 5 — heading: `5 — LEAVE WITH SOMETHING TO DO`

Three equal rounded rectangles side by side, all filled in the accent green, single bold line
each:

1. **A credential you could start now**
2. **A graduate step, and who takes it**
3. **Employers, in your state**

## The return connector

One curved arrow in **blue**, thicker than the others, running up the right-hand margin from
the right edge of Band 3 to the right edge of the four mode boxes in Band 2. Arrowhead at the
Band 2 end.

Place this text beside it in the right margin, in blue uppercase:

> **EVERY RESULT IS THE NEXT QUESTION**

and under it, in smaller plain grey text:

> Click any employer, field, credential or job and it becomes the new pole.

## Styling

- Canvas background `#F1F2EE`. Shape fill `#E8EAE3`. Text `#161A17`, secondary text `#4E554E`.
- Accent green `#0A8F5C` — used for the explorer header, the two named modes, the **Ways in**
  box, the Band 5 boxes, and every forward arrow.
- Blue `#2262B4` — used **only** for the return connector and its label. Nothing else is blue.
- Green-filled shapes use a pale green fill `#E2F1E9` with a `#0A8F5C` outline.
- Serif headings, sans-serif body, monospace for the band headings and the small uppercase
  condition lines. Corner radius 5px on every shape.
- Forward arrows: thin, solid, single arrowhead. Only the arrows I have labelled get labels;
  the rest are unlabelled.

## Do not include

No status badges, no build states, no percentages, no data counts other than the label text
above, no legend, no timeline, no swimlane titles down the left edge, no decision diamonds, no
start or end terminators, and no icons or emoji anywhere.
