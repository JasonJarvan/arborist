### Arborist subagent brand contract

Contract: `ARBORIST-BRAND-COMPAT:v1`

- Keep an L2 Impler and every L1 worker on a same-brand chain: `effective_subagent_brand = impler.spec.brand`.
- For `brand=codex`, dispatch implementation, TDD, refactoring, Explore, check, challenge, and research only to Codex subagents. Never pretend the session is Claude Code.
- For `brand=claude-code`, dispatch those activities only to Claude Code subagents and use the configured Claude agent/model tier.
- A missing or unsupported brand, an untruthful runtime registration, or a brand mismatch is a hard error. Stop instead of guessing a default or crossing providers.
- A human-direct harness session that does not participate in agent discovery or routing is exempt from registration.
- The host route config is `<REPO_ROOT>/.work_context/sendbox/_handoff-config.yaml`. Handoff and inherit MUST receive this absolute path explicitly; do not rely on the protocol's default config discovery.
