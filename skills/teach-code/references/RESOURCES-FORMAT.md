# RESOURCES.md Format

`RESOURCES.md` is the curated set of trusted sources for this topic. Knowledge for explainers should be drawn from here, not from parametric guesses. Wisdom comes from the communities listed here.

## Structure

```md
# {Topic} Resources

## Knowledge

- [Official API Documentation: `{Library/Framework}`](https://example.com/docs)
  Primary reference by the maintainers covering core architecture, API signatures, and lifecycle semantics. Use for: authoritative explanations of types, functions, and runtime behavior.
- [Official User Guide: `{Testing/Verification Tool}`](https://example.com/testing)
  Official documentation for automated testing and verification. Use for: designing high-signal test assertions and verification labs in every lesson.

## Wisdom (Communities)

- [`{org/repo}` GitHub Discussions](https://github.com/example/repo/discussions)
  Official Q&A and architecture forum monitored by maintainers and experienced practitioners. Use for: design review, performance tuning, and idiomatic patterns.
- [{Language/Framework} Users Forum](https://example.com/forum)
  High-signal, well-moderated forum for learners and experts alike. Use for: architectural questions and real-world debugging discussions.
```

## Rules

- **High-trust only.** Prefer primary sources, official documentation, recognised experts, peer-reviewed work, verified workspace skills (`.agents/skills/*`), and communities with strong moderation. If a resource is marketing dressed as education, leave it out.
- **Annotate every entry.** A bare link is useless in three months. Add one line: what it covers and when to reach for it.
- **Group by Knowledge / Wisdom.** Mirrors the philosophy in [SKILL.md](../SKILL.md). It is fine for a resource to appear in only one group.
- **Surface gaps explicitly.** If no good resource exists for an area the mission needs, write a `## Gaps` section listing what is missing. This drives future search.
- **Prune ruthlessly.** A resource that turned out to be wrong, shallow, or off-mission should be removed, not buried. Better five sharp sources than thirty mediocre ones.
- **Record community preferences.** If the user has opted out of joining communities, note it here so future sessions don't keep proposing them.
