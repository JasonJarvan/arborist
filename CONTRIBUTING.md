# Contributing to Arborist

Arborist is a corpus of **generalized engineering discipline** — reusable guides, methodology
clusters, config templates, and adopt/sync tooling that sit as an overlay on top of Trellis.
Contributions that make that discipline sharper, more general, or easier to adopt are welcome.

## What Arborist is (and is not)

- **Is:** original, generalized docs / scripts / config templates. Everything ships under Apache-2.0.
- **Is not:** a fork or redistribution of its dependencies. Trellis is **AGPL-3.0** and is
  installed separately by the adopter; Arborist only interoperates with it via its CLI. See
  [`NOTICE`](./NOTICE).

## Ground rules (please read before opening a PR)

1. **Keep it generalized.** Guides use placeholders — `<REPO_ROOT>`, `<project>`, `<HOME>` — not
   concrete values. No absolute machine paths, no internal/organization repo names, no secrets,
   no UUIDs, no emails. A worked example must stay anonymized.
2. **No AGPL-sourced text.** Do not paste text copied out of Trellis factory files (its
   `workflow.md`, guides, prompts, etc.) into Arborist. Arborist accepts **original** content only. If you
   are describing how a dependency behaves, write it in your own words.
3. **Do not touch `LICENSE` or `NOTICE`** unless the change is specifically a licensing correction.
4. **English commits and PRs** for anything in this public repo.
5. **Run the self-check before pushing:**
   ```bash
   grep -rnE "/home/|/Users/|@[A-Za-z0-9._-]+\.(com|ai|io)|[0-9a-f]{8}-[0-9a-f]{4}" . \
     --exclude-dir=.git --exclude-dir=.harness-vcs --exclude-dir=.trellis
   ```
   The only expected hits are this command's own pattern (in this file) and the detection regexes in
   [`skills/arborist-sync/sync.sh`](./skills/arborist-sync/sync.sh). Any real hit — an absolute path, an email,
   a UUID, or an internal repo/project name — must be removed before you push.

## How to contribute

### A guide or a methodology cluster

- Guides live in [`overlay/spec/guides/`](./overlay/spec/guides/); methodology clusters in
  [`overlay/spec/guides/methodology/`](./overlay/spec/guides/methodology/).
- Add or update the guide, then **update the index tables** so it stays discoverable:
  [`overlay/spec/guides/index.md`](./overlay/spec/guides/index.md) and, for methodology,
  [`overlay/spec/guides/methodology/index.md`](./overlay/spec/guides/methodology/index.md).
- Keep the "when to read" cue accurate — that column is how agents route to your guide.
- If your change encodes a durable, hard-to-reverse architectural decision, record it as an ADR
  under [`overlay/spec/guides/decisions/`](./overlay/spec/guides/decisions/) using the
  [template](./overlay/spec/guides/decisions/TEMPLATE.md), and register it in the ADR index.

### Adopt / sync tooling

- `adopt.sh`, `INSTALL.md`, `ADOPT.md`, and the [`arborist-sync`](./skills/arborist-sync/SKILL.md) skill
  govern how an instance repo picks up and syncs the overlay. Keep the placeholder-integrity and
  privacy gates intact — they are what keep the template repo generic.

### Fixing links / consistency

- All relative links in the READMEs and guide indexes must resolve. If you move or rename a guide,
  propagate the rename to every index and cross-link.

## Syncing improvements upstream from an instance

If you run Arborist in a real repo and improve a guide there, the intended path back upstream is the
[`arborist-sync`](./skills/arborist-sync/SKILL.md) skill: it de-privatizes the change, checks for
AGPL-sourced text, verifies placeholder integrity, and mediates conflicts before it lands here.
Do not push instance-specific values (ledger IDs, `<project>` values, absolute machine paths).

## Certifying your contribution

By opening a PR you affirm that the contribution is your own original work (or that you have the
right to submit it), that it contains no AGPL-sourced text, and that you agree to license it under
Apache-2.0.
