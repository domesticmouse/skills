# Skills

A collection of AI agent skills by [@domesticmouse](https://github.com/domesticmouse), compatible with [skills.sh](https://skills.sh).

## Installation

Install all skills or pick interactively:

```bash
npx skills add domesticmouse/skills
```

Install a specific skill:

```bash
npx skills add domesticmouse/skills --skill <skill-name>
```

## Available Skills

### [`bjm-voice`](skills/bjm-voice/SKILL.md)

Guides the agent in writing, editing, or reviewing blog posts, tutorials, articles, and social media updates in Brett Morgan's authentic writing voice.

**Origin:** Distilled from analysis of Brett's existing articles, technical write-ups, and social posts to capture recurring linguistic signatures, Australian English spelling, and conversational cadence.

**Intended Usage:** Explicitly invoke with `/bjm-voice` (or ask the agent to use `bjm-voice`) when drafting, editing, or reviewing a Medium post, LinkedIn update, or article that should sound like Brett. Configured as opt-in only so it won't bleed into everyday documentation, READMEs, or general writing tasks uninvited.

## Repository Structure

Each skill lives in its own directory under `skills/`:

```text
skills/
└── <skill-name>/
    ├── SKILL.md        # Required: YAML frontmatter (name, description) + instructions
    ├── references/     # Optional: additional documentation loaded on demand
    ├── scripts/        # Optional: helper scripts and utilities
    └── assets/         # Optional: templates and static resources
```

## License

See [LICENSE](LICENSE) for details.

## Disclaimer

This is not an officially supported Google product.

