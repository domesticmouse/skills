---
name: teach-code
description: >-
  Interactive, stateful code-teaching workflow that builds self-contained HTML
  lessons (compiled from Markdown via build.py), printable reference sheets,
  learning records, and runnable per-lesson companion projects in ./apps/
  verified with automated tests and linters. Use when the user asks to learn a
  programming language, framework, or engineering tool, build or extend an
  interactive coding course, create lessons or reference sheets, or invokes
  /teach-code or /teach.
---

# Interactive Code-Teaching Workflow (`teach-code`)

The user has asked you to teach them a programming topic or build out interactive course materials. This is a stateful request — they intend to learn the topic over multiple sessions by building real, verified software.

## Teaching Workspace (`.` or `./tutorial/`)

By default, use the repository root (`.`) as the teaching workspace for dedicated course repositories, or `./tutorial/` when adding a course inside an existing project repository (so root project files remain untouched). All course paths below are relative to the chosen teaching workspace root, while `references/*-FORMAT.md` links resolve from this skill's directory:

- `MISSION.md`: A document capturing the _reason_ the user is interested in the topic. This grounds all teaching. Use the format in [MISSION-FORMAT.md](./references/MISSION-FORMAT.md).
- `reference/*.md`: A directory of Markdown reference materials (compiled to `reference/*.html` by `build.py`, with `GLOSSARY.md` compiling to `glossary.html`). These are the compressed learnings from the lessons — mental models, API/syntax cheat sheets, verification/testing guides, and glossaries. They are the raw units of learning, designed for quick lookup and clean printing.
- `RESOURCES.md`: A curated list of trusted primary sources, official documentation, and workspace skills (`.agents/skills/*`) used to ground your teaching in verified knowledge. Use the format in [RESOURCES-FORMAT.md](./references/RESOURCES-FORMAT.md).
- `learning-records/*.md`: A directory of learning records capturing what the user has learned. These are loosely equivalent to architectural decision records (ADRs) — they capture non-obvious lessons, prior knowledge, and key insights that drive future sessions and calculate the zone of proximal development. Titled `0001-<dash-case-name>.md`, incrementing sequentially. Use the format in [LEARNING-RECORD-FORMAT.md](./references/LEARNING-RECORD-FORMAT.md).
- `lessons/*.md`: A directory of Markdown lesson sources (compiled to `lessons/*.html` by `build.py`). A **lesson** is a single, self-contained tutorial unit that teaches one tightly-scoped concept or capability paired with an automated verification gate tied to the mission. This is the primary unit of teaching in this workspace.
- `index.md`: The Markdown course landing page (compiled to `index.html` by `build.py`) for local browsing and GitHub Pages hosting, auto-rendering lesson cards via `{{widget:lesson-cards}}` and reference sheet links/cards via `{{widget:reference-cards}}`.
- `build.py`: The Markdown-to-HTML static site builder (`markdown-it-py` + `pyyaml`). Only `.md` source files are tracked in Git (`index.html`, `lessons/*.html`, and `reference/*.html` are gitignored and generated locally via `.venv/bin/python build.py --check` or in CI via `.github/workflows/pages.yml`).
- `apps/<NNNN-lesson-slug>/`: A series of runnable project directories where each directory represents the exact, verifiable state of the companion application or script after completing the corresponding lesson (`lessons/<NNNN-lesson-slug>.md`).
- `assets/*`: Reusable **components** shared across lessons (`style.css`, `course.js`, quiz/exercise widgets, interactive simulators). See [Assets](#assets).
- `README.md`: Repository overview linking to the live GitHub Pages site (when hosted), published lessons, reference sheets, and license.
- `NOTES.md`: A scratchpad for recording user preferences, the curriculum roadmap, and working notes.

## Philosophy

To learn at a deep level, the user needs three things:

- **Knowledge**, captured from high-quality, high-trust resources (official language/framework documentation, primary texts, and any verified `.agents/skills/*` reference guides in the repository).
- **Skills**, acquired through highly-relevant interactive lessons devised by you, based on the knowledge.
- **Wisdom**, which comes from interacting with other learners and practitioners in real-world communities.

Before `RESOURCES.md` is well-populated, your focus should be to catalog high-quality resources (both external primary documentation and any verified `.agents/skills/*` skills in the workspace) to help the user acquire knowledge. Never trust unverified parametric knowledge when a compiler check, test suite, linter, script, or official documentation lookup can verify it.

### Fluency vs Storage Strength

Always distinguish between two types of learning:

- **Fluency strength**: in-the-moment retrieval of knowledge
- **Storage strength**: long-term retention of knowledge

Fluency can give an illusory sense of mastery, whereas storage strength is the real goal. Design lessons that build long-term retention through desirable difficulty:

- **Retrieval practice**: Recall from memory via interactive fill-in-the-blank code exercises and multiple-choice quizzes.
- **Spacing**: Distributing practice and revisiting earlier concepts across lessons.
- **Interleaving**: Mixing related skills (e.g., data modeling, API usage, error handling, and test assertions) within exercises and verification labs.

## Lessons & Markdown-to-HTML Pipeline (`build.py`)

A lesson is the primary artifact you produce: the unit in which knowledge and skills reach the user. Each lesson is authored as a clean Markdown file saved to `lessons/` and titled `0001-<dash-case-name>.md` (or starting at `0000-<dash-case-name>.md` / `0001-<dash-case-name>.md` for environment and project bootstrap), then compiled to HTML (`lessons/<NNNN-slug>.html`) by running `.venv/bin/python build.py --check`.

When teaching a programming language, framework, or tool where subsequent lessons need a configured project manifest, virtual environment, linter, and test runner, start with a bootstrap lesson covering project initialization, dependency setup, entry-point wiring, and test/lint configuration so every subsequent lesson builds on a concrete, runnable foundation.

### Explaining Code: Block-by-Block Walkthrough Followed by Full Context

When introducing or modifying code in a lesson, use the **Block-by-Block + In-Context** pattern to keep cognitive load low while giving the learner a self-contained, runnable reference:

1. **Start from Nothing & Grow the Code Inline (Never Assume External File References):**
   - Never write lesson prose assuming the learner has `apps/<NNNN-slug>/...` open in another window, and never link to relative source files outside the compiled site (such as `../apps/...`), which would 404 on GitHub Pages.
   - Start from a minimal foundation in the first lesson and progressively grow the codebase across lessons, showing both the newly added blocks step-by-step and the complete runnable code (with its verified terminal output) directly inside each lesson.
2. **Break Out Logical Blocks First (`### Block N: ...`):**
   - Instead of dropping a large file or function all at once and explaining it after the fact, split new or changed code into small, self-contained blocks (e.g., imports & configuration, data structures/types, core logic, inline tests).
   - For each block, show **only the relevant snippet** in a fenced code block, immediately followed by a focused bulleted breakdown unpacking the syntax, types, data flow, and API calls in that block.
3. **Show the Code in Full Context Next (`### Complete ... Listing`):**
   - After walking through the individual blocks, provide the complete source file or full surrounding module/function in context so the learner can see exactly how the pieces fit together and copy or compare the runnable code without guesswork.

### Markdown Directives & Frontmatter (`build.py`)

All course pages (`index.md`, `lessons/*.md`, `reference/*.md`) use YAML frontmatter (`title`, `page_title`, `nav_id`, `badge`, `subtitle`, plus `card` metadata for lessons and reference sheets, or `nav_label` for reference sheets) and clean Markdown directives compiled by `build.py`:

- **Tufte Sidenotes**: `{{sidenote:Inline Markdown note text...}}` (renders a numbered superscript `<span class="sidenote-number"></span><span class="sidenote">...</span>` in the right margin on wide viewports, or toggles inline on narrow screens).
- **Callouts & Teacher Prompts**: `:::callout` (plus optional variants like `:::callout-warn` and `:::callout-success` for recommended primary sources, warnings, and notes) and `:::teacher-prompt` (for next-step prompts and reminders to ask questions) ... `:::`
- **Code Blocks & Mermaid Diagrams**: Fenced code blocks with language identifiers and optional captions (e.g., ```` ```rust ````, ```` ```python ````, ```` ```bash caption="Optional caption" ````), and ```` ```mermaid caption="Figure N.1: ..." ```` (wrapped in `<figure class="mermaid-figure">`).
- **Tables**: Standard GFM pipe tables (`| ... |`), optionally preceded by `Table: Caption text`, automatically styled with `<table class="ref-table">`.
- **Interactive Fill-in-the-Blank Exercises**: `:::exercise id="ex-NNNN" title="Interactive Lab: ..." badge="Skill Practice • Tight Feedback Loop"` containing explanatory prose, a fenced code block with `{{blank:answer|error_hint|placeholder|width}}` tokens (use `||` inside `answer` for multi-answer alternatives like `size.x / 2.0||size.x * 0.5`), and a `:::prompts` YAML block with `hint` and `success` messages.
- **Verification & Test Coverage Gates**: `:::verify id="verify-NNNN" title="Verification Lab: ..." badge="..."` (with optional `tier`, `caught`, `missed` attributes when mutation testing is used) containing prose, test/verification commands and code blocks, and `- [ ]` step checklist items.
- **Multiple-Choice Quizzes**: `:::quiz id="quiz-NNNN" title="Retrieval Practice: ..." badge="3 Questions • Equal-Length Options"` with a YAML list of questions (`question`, `wrong_hint`, and 4 `options` with `letter`, `text`, `correct`, `explain`). `build.py --check` enforces that all 4 options within each question have identical word counts!
- **Interactive Widgets**: `{{widget:lesson-cards}}`, `{{widget:reference-cards}}`, and custom interactive simulators (`{{widget:<simulator-id>}}`) defined in `assets/course.js`.

### Runnable Per-Lesson Companion Apps (`apps/<NNNN-lesson-slug>/`)

Back every lesson with a real, runnable directory under `apps/<NNNN-lesson-slug>/` (matching the lesson filename stem):

1. **Static Site Builder Environment (`uv` for `build.py`):**
   - Use `.venv/bin/python build.py --check` (created via `uv venv` and `uv pip install markdown-it-py pyyaml`) to compile and validate all Markdown lessons, reference sheets, internal links, and quiz option word counts.
2. **Copy-Then-Apply Progression:**
   - Start at the first lesson (`apps/0001-.../`) and progressively grow the application across lessons.
   - For each subsequent lesson $N$, copy the previous lesson's directory into `apps/<N>/` (using copy-on-write such as `cp -cR` on macOS/APFS when build directories are cloned), apply the new lesson's code and test updates, and update file timestamps (`touch`) if reusing incremental build artifacts so the compiler or test runner always builds the new lesson's code.
3. **Execute, Lint, Test & Reconcile Lessons with Reality:**
   - Run the formatter, linter, test suite, and any mutation or verification tools taught in the lesson against `apps/<NNNN-slug>/`.
   - Ensure zero compiler/linter warnings and 100% passing tests (plus zero missed mutants when mutation testing is part of the workflow).
   - If anything does not line up between the runnable companion code/output and the lesson Markdown/HTML, reference sheets (`reference/*.md`), or interactive simulators (`assets/course.js`), update them immediately and re-run `.venv/bin/python build.py --check` so the course and runnable code stay 100% in sync.

### Visual Design, Layout Rules, Prism.js & Mermaid.js

A lesson should be **beautiful**, with clean, readable typography and layout (think Edward Tufte), since the user will return to these materials to review:

- **Tufte-inspired layout**: Pair a readable main prose column (`max-width` tuned for ~65–75 characters per line) with a dedicated right margin for numbered sidenotes (`{{sidenote:...}}`), while allowing tables, code listings, interactive simulators, and Mermaid figures to span cleanly without horizontal cramping.
- **Dark mode by default with `@media print` override**: Use dark mode across all lessons and `reference/*.html` documents (`<meta name="color-scheme" content="dark">` in `<head>` and `:root { color-scheme: dark; }` in `assets/style.css`), paired with a `@media print` light-mode override (hiding top navigation controls, bottom pagers, and interactive buttons) so lessons and reference sheets print cleanly on paper. Pair `scrollbar-color` on `:root` with `scrollbar-width: thin` (required on macOS so custom scrollbars render) and wrap legacy `::-webkit-scrollbar` fallbacks in `@supports not (scrollbar-color: auto)`. Use high-contrast `accent-color` tokens for interactive form controls.
- **Modern web typography, transitions, and accessibility**: Enable cross-document view transitions (`@view-transition { navigation: auto; }` inside `@media (prefers-reduced-motion: no-preference)`), style focus rings with `:focus-visible` and `outline-offset: 2px` via `:where(...)` (never bare `:focus`), apply `text-wrap: balance` to headings/table headers (`h1, h2, h3, th`) and `text-wrap: pretty` to body copy (`p, li, blockquote`), use semantic HTML landmarks (`<header>`, `<nav>`, `<main>`, `<article>`, `<footer>`), and ensure scrollable `<pre>` code blocks receive `tabindex="0"` for keyboard scrolling (handled automatically in `assets/course.js`).
- **Prism.js for syntax highlighting**: Format all code blocks with Prism.js (`<pre><code class="language-<lang>">`), and load the Prism `keep-markup` plugin when embedding interactive `<input>` fill-in-the-blank tokens inside code blocks. Never hand-roll syntax `<span>` tags.
- **Mermaid.js for diagrams**: Use Mermaid.js (`<pre class="mermaid">` configured with `theme: "dark"`, wrapped in `<figure class="mermaid-figure">`) for architecture, lifecycle, state-machine, data-flow, and hierarchy diagrams instead of ASCII-art diagrams.

### Course Index, Navigation & GitHub Pages Hosting

Keep the course navigable both locally and on GitHub Pages without cluttering the header bar:

1. **Minimal Tufte Breadcrumb Header & Bottom Pager (`build_nav_html` & `build_lesson_pager_html` in `build.py`):**
   - Never dump all individual lesson numbers (`0001`–`0030`) into `<nav class="course-nav">`. Keep the top bar high-signal and single-line using two flex groups:
     - **Left (`.nav-breadcrumbs`)**: Contextual breadcrumb trail (`Index › <Act/Section> › Lesson NNNN` on lessons where `<Act/Section>` links to `../index.html#<act-anchor>`, `Index › <Sheet Name>` on reference pages, and `Index` on the landing page) with `aria-current="page"` on the active item.
     - **Right (`.nav-controls`)**: On lesson pages, a compact `← Prev · Next →` pill group (`.nav-pager-group`) with full lesson title `title="..."` tooltips, separated by `|` from the reference sheet links (`Glossary`, cheat sheets) and `.mission-badge`.
   - **Bottom-of-Lesson Pagination Cards (`.lesson-pager`)**: `build_lesson_pager_html()` automatically appends a two-column `<nav class="lesson-pager" aria-label="Lesson pagination">` footer at the end of every lesson article with `← Previous • Lesson NNNN` and `Next • Lesson NNNN →` cards showing full lesson titles (and hidden in `@media print`).
2. **Synchronize Navigation & Index via `build.py --check` on Every New Lesson:** Whenever you add or update a lesson (`lessons/<NNNN-slug>.md`) or reference sheet (`reference/*.md`):
   - Populate its YAML frontmatter (`title`, `page_title`, `nav_id`, `badge`, `subtitle`, `card`), ensure `build.py` maps its `nav_id` to the appropriate section/act anchor on `index.md`, and add the link to `README.md`.
   - Run `.venv/bin/python build.py --check` so `build.py` automatically regenerates `<nav class="course-nav">` and `<nav class="lesson-pager">` across every page, updates the `.lesson-card` grid in `index.html`, compiles all `.md` files to `.html`, and validates equal-word-count quiz rules and internal `.md` links (rewritten to `.html`).
3. **GitHub Pages Deployment (`.github/workflows/pages.yml` & `.nojekyll`):**
   - When deploying to GitHub Pages, configure `.github/workflows/pages.yml` to run `python build.py --out-dir _site --check` to compile the Markdown sources directly into `_site/` (`index.html`, `.nojekyll`, `assets/`, `lessons/*.html`, `reference/*.html`) so companion code directories (`apps/`) and internal tracking files (`MISSION.md`, `RESOURCES.md`, `NOTES.md`, `learning-records/`) are excluded from the published web artifact.
   - Pass `env: NODE_OPTIONS: --no-deprecation` on the `actions/deploy-pages@v4` step to suppress the benign Node.js `[DEP0040] DeprecationWarning: The punycode module is deprecated` warning.

Each lesson should be short, focused, and completable quickly within working-memory limits, giving the user a single tangible win directly tied to the mission and within their zone of proximal development.

If possible, open the compiled lesson file for the user or provide a direct clickable link. Every lesson should:
- Link via Markdown/HTML anchors to adjacent lessons and `reference/*.md` (compiled to `reference/*.html`) documents.
- Recommend a primary source (such as the relevant official documentation page, specification, book chapter, or workspace skill reference).
- Include a reminder (`:::teacher-prompt`) to ask follow-up questions to the agent.

## Assets

Lessons are built from reusable **components** stored in `assets/`: stylesheets, quiz widgets, interactive simulators or visualizers, fill-in-the-blank code completion exercises, and anything else a second lesson could reuse.

Reuse is the default, not the exception. Before authoring a lesson, read `assets/` and build from the components already there. When a lesson needs something new and reusable, write it as a component in `assets/` and wire it into `build.py`; never inline code a future lesson would duplicate.

A shared dark-mode stylesheet (`assets/style.css`) and a shared script (`assets/course.js`) that centrally loads and configures **Prism.js** (including `keep-markup` and the target language grammars) and **Mermaid.js** (`theme: "dark"`) alongside reusable quiz, fill-in-the-blank code exercise, and simulator widgets are the foundational components of the workspace: every lesson and reference sheet links them so the course looks and behaves like one cohesive site.

## The Mission

Every lesson should be tied into the mission — the reason the user is learning the topic, captured in `MISSION.md`.

If the user is unclear about aspects of the mission, or `MISSION.md` is not yet populated, ask clarifying questions **one at a time** to confirm their concrete goal, starting point, and what success looks like.

Missions may evolve as the user develops more skills and knowledge. Update `MISSION.md` and add a learning record when the mission shifts, confirming with the user first.

## Zone Of Proximal Development

Each lesson should challenge the user "just enough". Determine the next lesson by:

- Reading `learning-records/`
- Checking what has already been built in `lessons/` and `apps/`
- Selecting the next step toward the mission in `MISSION.md` and `NOTES.md`

## Knowledge & Skills

- **Knowledge**: Design each lesson around a concrete skill. Present only the knowledge required to acquire that skill, backed by citations to `RESOURCES.md` and `reference/*.html`. Keep cognitive load low during knowledge acquisition by breaking out new code block by block, explaining each snippet in isolation, and then showing the full code in context.
- **Skills**: Build durability through effortful retrieval and immediate feedback loops:
  - Interactive fill-in-the-blank code blocks (using `:::exercise` and Prism `keep-markup`).
  - Multiple-choice retrieval quizzes (`:::quiz`) with immediate feedback. **Quiz rule**: Every option within a quiz question must have the exact same word count (and similar character length), with the correct answer position varied across questions so formatting or length never leaks the answer.
  - Hands-on terminal verification, testing, and linting steps (`:::verify`).

## Acquiring Wisdom

Wisdom comes from testing skills in real-world engineering communities (e.g., official project GitHub Discussions, Discord/Zulip servers, and moderated language/framework forums). Include high-signal communities in `RESOURCES.md` while respecting any user preferences regarding community participation.

## Reference Documents

While creating lessons, maintain `reference/*.md` cheat sheets (compiled to `reference/*.html` by `build.py`) — the compressed essence of the lessons designed for quick reference and clean printing (e.g., mental model & API cheat sheets, testing & verification cheat sheets, and a Glossary following [GLOSSARY-FORMAT.md](./references/GLOSSARY-FORMAT.md)). Once a glossary is created, adhere to its terminology across every lesson.

## `NOTES.md`

Record any teaching preferences, curriculum roadmaps, or workflow notes expressed by the user in `NOTES.md` and consult it before designing each lesson.
