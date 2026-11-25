---
name: readable-artifact
description: "Guide for building a Claude Artifact page that someone who was not part of the work understands quickly, shown in visuals first with little text. Use for any page meant for other people to read."
argument-hint: "Who reads the page, what they will decide or do after reading, whether they know the field, and whether they took part in the work"
disable-model-invocation: true
---

# Readable Artifact

A page people read once, quickly, often without the context of the work behind it. The test: **someone who was not part of the work opens the page and understands the main point, why it holds, and what it means for them, without asking anyone.**

**Readability comes from showing each point clearly, not from volume.** A scene is the content of one tab, and a visual is what a scene uses to show its point, such as a timeline or a table. A visual shows a structure at once, while prose makes the reader build it in their head. So show each point in a visual first, and use a sentence only when no visual fits. More scenes and more text do not make a point clearer.

Write the page in the user's language. The artifact tool's own rules govern the page skeleton, allowed CDNs, responsiveness, and title.

## Workflow

Take the steps in order. Do not start a step until the previous step's "Done when" holds.

1. **Decide who reads the page: what they will do after reading, what they know about the field, and whether they took part in the work.** Done when each of the three has exactly one value from `references/audiences.md`, stated in the invocation arguments or in this request. If a value is not stated there, ask in your reply before building, even when an earlier conversation suggests one.
2. **Write the main point in one sentence.** Done when the sentence answers the question the reader opens the page with.
3. **Choose the scenes the reader needs and their order.** Done when every item in "Check the scenes" in `references/storytelling.md` holds.
4. **Decide each scene's label, heading, and visual.** Done when every rule in "Labels and headings" below holds, and each visual has the same shape as its scene's answer. Choose the visual with the table in `references/storytelling.md`.
5. **Choose the words and the level of detail for the reader.** Done when every item in "Check the words" in `references/audiences.md` holds for the plan.
6. **Build the page by the Screen rules below.** Done when each scene shows the label, heading, and visual decided in step 4.
7. **Check the rendered page as the reader.** Done when each visual appears on screen as planned in step 4 and shows its point without reading the text, no sentence repeats what the visual already shows, and every item in "Check the words" holds for the text on the page. Look at each scene on screen when a tool in this session can show the page; when none can, read the source and say so in your reply. If a check fails, fix the step where that part was decided, then rebuild.

## Labels and headings

- **Labels, the names in the tab list, are very short word combinations that make clear what the scene delivers.** Not necessarily a single word; the requirement is that the reader knows from the label alone what they will get there.
- **No full sentences and no internal jargon in labels.** A long label is a sign the scene's point is not yet clear.
- **Read in order, the labels outline the whole page.**
- **The scene heading states the scene's point in one short sentence.**

## Screen

- **Tabs on the left, one scene visible at a time.** Tabs switch with a click and with the arrow keys. On narrow screens the tabs become a horizontal bar at the top. Previous and next buttons sit under each scene.
- **Every structural device has a meaning.** Numbers mark a real sequence. A dashed line separates the unsettled tab, the final tab for what is not yet decided or confirmed, from the scenes. A heavy blue border goes around the one box that matters most in a scene, never around table cells. That box keeps its meaning color inside the border. Nothing is styled for decoration.
- **Each color has one meaning for the whole page:** green for solved, allowed, or proceeding, red for a problem, blocked, or failing, amber for exceptions and caution, blue only for the heavy border. Everything else stays neutral.
- **White single theme** with every color set explicitly.

## Content

- **A scene holds its heading, at most one visual that shows its point, and only the text that visual cannot show.** When the visual shows the point, do not restate it in prose.
- **Remove what the reader will not act on**, even if it was part of the work. The reader's attention is what the page spends, and every sentence uses some of it. When a scene has much text, the reader reads instead of looking, and the sentences they need are lost among the rest. The page is not the record of the work, so leaving a detail off loses nothing. When unsure, leave it off.
- **Keep the reason next to the main point and each decision.** A conclusion without its reason cannot be understood by someone who was not there.
- **Make ownership visible.** Wherever a judgment appears, the reader sees which role makes it and which role only handles exceptions.
- **Explain through a concrete case from the page's own subject** rather than an abstract statement of the rule.
- **Refer to everything by its name, not by a number, a code you made up, or its position.** The reader does not share the map you built while working, so "step 3" or "P1" means nothing to them. Write "before the BE live deploy", not "before step 3".
- **Separate what is verified from what is inferred.** Never present a guess as fact. Label an inference, or move it to the unsettled tab. Remove that content once it is settled.
- **The page is understood without following any link.**
- **One sentence per line.** A list item is a bold lead followed by short lines, never several sentences packed together.
