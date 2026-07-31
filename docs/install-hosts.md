# Destination installation guide

This repository ships thirteen `resume-<source>` Skills to thirteen destination hosts (derived from registries). The reader remains offline and stdlib-only; plugin/marketplace packages contain the same inert Skills and no network integration.

## Build or inspect packages

```bash
PYTHONPATH=src python3 scripts/install-resume-skills hosts --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix
python3 scripts/build_host_packages.py --output-dir host-packages
```

The package builder creates thirteen `*-<host>-skills.zip` archives (one per
enabled destination, including Pi, OpenClaw, goose, Crush, Cline, OpenHands, Hermes, GitHub Copilot CLI, and Gemini CLI), seven supported
plugin/marketplace archives, and `host-packages.json` (`host-packages-v2`) with
SHA-256 digests, per-artifact offline `contract_id` validation (#27), and honest
`native_evidence_status=not-run` until host CLI revalidation is recorded.
Published `0.3.4` release assets remain historical nine-destination archives;
current `main` builds thirteen. Replace `<version>` below with the release version.

Download and verify an exact release before installing a plugin:

```bash
gh release download "v<version>" \
  --repo ImL1s/resume-skills \
  --dir "portable-resume-<version>"
cd "portable-resume-<version>"

# Linux
sha256sum --check SHA256SUMS

# macOS
shasum -a 256 --check SHA256SUMS
```

Starting with `v0.3.2`, checksum entries use the flat filenames delivered by a
GitHub Release. The release workflow validates that layout on both Ubuntu and
macOS before publication.

## Fastest safe install

From PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen        # user-global Qwen profile
install-resume-skills quick-install all         # all thirteen user-global profiles
install-resume-skills quick-install qwen --project "$PWD"
```

From a source checkout, use `pipx install .` instead. Both routes install the
same two CLI entry points. `quick-install` defaults to user-global roots; use
the lower-level transactional commands below for dry runs, explicit roots,
verification, backup replacement, or uninstall.

## Public marketplace install

The independent
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
publishes host-native catalogs for the six compatible hosts. These commands
were verified against the public repository for version `0.3.2`:

### Claude Code

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
```

### Codex

```bash
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

### Cursor Agent

```bash
cursor-agent plugin marketplace add \
  https://github.com/ImL1s/portable-resume-marketplace --git-ref main
```

Run `/plugin`, open **Marketplace**, search for `portable-resume`, and install
it for user scope.

### Qwen Code

```bash
qwen extensions sources add ImL1s/portable-resume-marketplace
qwen extensions install \
  ImL1s/portable-resume-marketplace:portable-resume \
  --consent --scope user
```

### Grok CLI

```bash
grok plugin marketplace add ImL1s/portable-resume-marketplace
grok plugin install portable-resume@portable-resume-marketplace --trust
```

### Kimi Code CLI

Inside Kimi Code CLI, add the catalog:

```text
/plugins marketplace https://raw.githubusercontent.com/ImL1s/portable-resume-marketplace/main/kimi-marketplace.json
```

Select **Portable Resume**, choose **Trust and install**, then confirm with
`/plugins list`.

Antigravity and OpenCode do not currently expose a compatible public catalog
for these inert Skill packages. Use the published release/plugin or direct
Skill routes below. Network access is used only by the destination host to
download a package; every bundled reader remains offline.

## Direct installer (all hosts)

```bash
# Preview, install, verify, then uninstall one profile
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD" --dry-run
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host qwen --scope project --project "$PWD"
PYTHONPATH=src python3 scripts/install-resume-skills verify \
  --host qwen --scope project --project "$PWD"
PYTHONPATH=src python3 scripts/install-resume-skills uninstall \
  --host qwen --scope project --project "$PWD"
```

Use `--scope global` for the user root or `--root <path>` for an explicit root. `--host all` locks every unique physical root in a deterministic order, replans under those locks, then mutates; if a later root fails, same-process compensation restores earlier roots while the locks remain held (not durable multi-root atomicity across process crash — use `recover` per root). Direct Skill payloads are **host-neutral** (`agent-skills-portable-v1`): Codex and Antigravity can both claim the natural project root `.agents/skills` with one set of `resume-*` bytes. Host-specific activation grammar lives in `install-resume-skills hosts --json` / this guide, not in the shared Skill body. Genuine same-path content divergence still fails with `E_INSTALL_CONFLICT` before mutation.

## Per-host routes

| Host | Direct Skill root (project / user) | Preferred package route | Activation |
|---|---|---|---|
| Claude Code (`claude`) | `.claude/skills` / `~/.claude/skills` | Public marketplace commands above. Offline fallback: extract `claude-marketplace.zip`, add its root, then install `portable-resume@portable-resume`. | `/resume-codex` |
| Codex (`codex`) | `.agents/skills` / `~/.agents/skills` | Public marketplace commands above. Offline fallback: extract `codex-marketplace.zip`, add its root, then install `portable-resume@portable-resume`. | `$resume-codex`; `/skills` lists |
| Cursor (`cursor`) | `.cursor/skills` / `~/.cursor/skills` | Add the public Git marketplace, then install from `/plugin`. Offline fallback: use `cursor-agent --plugin-dir <.../plugins/portable-resume>`. | `/resume-codex` |
| OpenCode (`opencode`) | `.opencode/skills` / `~/.config/opencode/skills` | Direct Skill only. OpenCode plugins are executable JS/TS modules, not a packaging format for inert Skills. | Ask it to use `resume-codex` |
| Antigravity (`antigravity`) | `.agents/skills` / `~/.gemini/config/skills` | Extract `antigravity-plugin.zip`; `agy plugin validate <extracted-dir>`, then `agy plugin install <extracted-dir>`. Manual fallback: `.agents/plugins/portable-resume` or `~/.gemini/config/plugins/portable-resume`. | Mention `resume-codex`; `/skills` lists |
| Grok Build (`grok`) | `.grok/skills` / `~/.grok/skills` | Public marketplace commands above. Offline fallback: validate and install the extracted `grok-plugin.zip` with `--trust`. | `/resume-codex` |
| Qwen Code (`qwen`) | `.qwen/skills` / `~/.qwen/skills` | Public extension source commands above. Offline fallback: `qwen extensions install /path/portable-resume-<version>-qwen-extension.zip`. | `/resume-codex`; `/skills` lists |
| Kimi Code CLI (`kimi`) | `.kimi-code/skills` / `$KIMI_CODE_HOME/skills` (default `~/.kimi-code/skills`) | Add the public catalog in `/plugins`, or install the exact release ZIP URL/path. Run `/plugins reload`, `/reload`, or start a new session. | `/skill:resume-codex` |
| Pi agent (`pi`) | `.pi/skills` / `~/.pi/agent/skills` | Direct Skill only for this PR. Alternate `.agents/skills` roots are compatibility-only (not multi-installed). | `/skill:resume-codex` |
| OpenClaw (`openclaw`) | `skills/` / `~/.openclaw/skills` | Direct Skill only. Alternate `.agents/skills` roots are compatibility-only. Native `openclaw skills install` route is not-run. | Load `resume-openclaw` / `resume-<source>` from the skills tree |
| goose (`goose`) | `.goose/skills` / `~/.config/goose/skills` | Direct Skill only. Legacy JSONL out of scope. Native goose UI not-run. | Load `resume-goose` / `resume-<source>` |
| Crush (`crush`) | `.crush/skills` / `~/.config/crush/skills` | Direct Skill only. Per-project crush.db. Native Crush UI not-run. | Load `resume-crush` / `resume-<source>` |
| Cline (`cline`) | `.cline/skills` / `~/.cline/skills` | Direct Skill only. Index+JSON authority. Native Cline UI not-run. | Load `resume-cline` / `resume-<source>` |
| OpenHands (`openhands`) | `.agents/skills` / `~/.openhands/skills` | Direct Skill only. Local CLI events. Native OpenHands UI not-run. | Load `resume-openhands` / `resume-<source>` |
| Hermes (`hermes`) | `.hermes/skills` / `~/.hermes/skills` | Direct Skill only. state.db schema 23. Native Hermes UI not-run. | Load `resume-hermes` / `resume-<source>` |
| GitHub Copilot CLI (`github-copilot`) | `.github/skills` / `$COPILOT_HOME/skills` | **Destination-only**. Compat `.agents`/`.claude` skills. No copilot source adapter yet. Native CLI install not-run. | Load installed `resume-<source>` skills |
| Gemini CLI (`gemini`) | `.gemini/skills` / `~/.gemini/skills` | **Compat profile** (not Antigravity). Session JSONL under `tmp/<hash>/chats`. Native UI not-run. | Load `resume-gemini` / `resume-<source>` |

For direct archives, extract the archive contents into the selected Skill root. Each archive contains `resume-antigravity`, `resume-claude`, `resume-codex`, `resume-cursor`, `resume-grok`, `resume-kimi`, `resume-opencode`, `resume-crush`, `resume-goose`, `resume-openclaw`, `resume-pi`, and `resume-qwen`.

## Host-specific notes

- **Claude:** cloud/Cowork sessions do not automatically read local user Skills; use project or account-enabled Skills there.
- **Codex/Cursor/OpenCode/Kimi:** compatible `.agents/skills` roots may cause duplicate names. Keep one authoritative copy per host and inspect discovery when upgrading.
- **Qwen:** do not install the source monorepo URL as an extension. Use the
  dedicated public marketplace source or the exact Qwen extension ZIP.
- **Kimi:** the destination bundle targets current Kimi Code CLI. Legacy Python Kimi CLI session data is readable as a source, but its plugin format and `~/.kimi` data root are different.
- **All plugin routes:** plugins can have broader execution authority than Skills. Inspect the archive and verify its published SHA-256 first.

## Project-scope shareable payload vs local control state (#33)

Direct project installs write two classes of files under the Skill root:

| Class | Path | Commit? |
|---|---|---|
| Shareable payload | `resume-*/`, `.portable-resume/runtime/`, `.portable-resume/resources/`, `.portable-resume/.gitignore` | Yes (deterministic) |
| Machine-local control | `.portable-resume/.state/` (manifest, lock, journal, backups, stage) | **No** — ignored by generated `.gitignore` |

Do not commit `.portable-resume/.state/`. Teammates checking out the shareable tree should run `install-resume-skills install …` (or verify after a local install) so each machine gets its own control state. Global/user installs use the same layout; the ignore file is harmless there.

## Duplicate / shadow Skill audit (#34)

Several hosts load Skills from more than one discovery root. The installer only
mutates the selected root; a higher-precedence stale copy can still win at
runtime.

```bash
# Read-only scan (bounded known roots + resume-* names only)
PYTHONPATH=src python3 scripts/install-resume-skills audit-host \
  --host cursor --scope project --project "$PWD"

# Install preflight: known higher-precedence divergent copy → E_INSTALL_SHADOW
PYTHONPATH=src python3 scripts/install-resume-skills install \
  --host cursor --scope global --project "$PWD" --home "$HOME" --dry-run
```

Safe consolidation workflow:

1. Run `audit-host` for the host/scope you care about.
2. Prefer one authoritative root (usually the installer's primary project or
   user root for that host).
3. Manually remove or rename **foreign** older copies after you confirm the
   installer-owned tree verifies. The tool never deletes alternate roots.
4. Re-run `audit-host` / `verify` until aggregate status is `unique` or
   `duplicate_identical_payload` / `same_physical_root_multi_claim`.

`hosts --json` includes machine-readable `discovery_roots` (precedence may be
`null` when host docs do not prove order). Equal first-class roots (for example
Cursor `.cursor/skills` vs `.agents/skills`) warn on divergent payloads but do
not block. Shared physical roots with multi-claim ownership are not treated as
harmful duplicates.

## Evidence boundary

Current `main` claims registry-derived **13×13=169** packaging and installed-runner
cells (including Pi, OpenClaw, goose, Crush, and Cline filesystem destinations). Published `0.3.4`
remains historical **9×9=81**. Historical `0.3.2` / `0.3.3` evidence covered
**64/64** cells. Exact `0.3.2` local package installation passed on all seven
supported native plugin/extension surfaces, including Cursor. Host-native
headless Skill invocation and public marketplace picker flows for fresh
OpenClaw/Pi native UI remain **not-run**. Versions, commands, and archive
digests are recorded in [`host-ui-smoke.md`](host-ui-smoke.md). Other visual
Skill pickers and vendor-curated directory listings remain separate unclaimed
gates.
