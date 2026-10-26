# GLOSSARY.md Format

`reference/GLOSSARY.md` (compiled to `reference/glossary.html` by `build.py`) is the canonical language for this teaching workspace. All explainers, exercises, and learning records should adhere to its terminology. Building it is itself part of learning: compressing a concept into a tight definition is evidence the user understands it.

## Structure

```md
---
title: "Glossary of {Topic} Terms"
page_title: "Glossary — {Topic}"
nav_id: "glossary"
nav_label: "Glossary"
badge: "Mission: {Mission Name}"
subtitle: "Canonical definitions used across all lessons and reference sheets. Designed for quick screen lookup and clean printing."
card:
  title: "**Glossary of {Topic} Terms**"
  summary: "{One-sentence summary of what the glossary covers for the index reference table.}"
---

## 1. {Category Heading}

**{Canonical Term}**:
{One or two sentences defining what the term IS in precise, unambiguous language.}
_Avoid_: {Common aliases or imprecise synonyms to avoid in this course}

**{Second Term}**:
{One or two sentences defining what the term IS, reusing earlier glossary terms where applicable.}
_Avoid_: {Aliases to avoid}
```

## Rules

- **Add a term only when the user understands it.** The glossary is a record of compressed knowledge, not a dictionary the user reads to learn. If the user has just been introduced to a concept, wait until they can use it correctly before promoting it here.
- **Be opinionated.** When several words exist for the same concept, pick the best one and list the rest as aliases to avoid. This is how language compresses.
- **Keep definitions tight.** One or two sentences. Define what the term IS, not what it does or how to do it.
- **Use the glossary's own terms inside definitions.** Once a term is in the glossary, prefer it everywhere, including inside other definitions. This is what makes complex terms easier to grasp later.
- **Group under subheadings** when natural clusters emerge (e.g., `## 1. Core Architecture`, `## 2. Verification & Testing`). A flat list or structured table is fine when terms cohere.
- **Flag ambiguities explicitly.** If a term is used loosely in the wider field, note the resolution for this workspace.
- **Revise as understanding deepens.** A definition written in lesson one may be refined later. Update in place; do not leave stale entries.
