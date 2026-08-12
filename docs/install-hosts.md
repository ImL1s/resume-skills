# Destination installation guide

<!-- generated:matrix-summary:begin (run scripts/render_docs.py --write) -->
This repository ships **17** enabled source Skills to **18** destination hosts (registry-derived; currently **17×18=306** cells).
<!-- generated:matrix-summary:end (run scripts/render_docs.py --write) -->

The reader remains offline and stdlib-only; plugin/marketplace packages contain the same inert Skills and no network integration.

## Build or inspect packages

```bash
PYTHONPATH=src python3 scripts/install-resume-skills hosts --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix
python3 scripts/build_host_packages.py --output-dir host-packages
```

The package builder creates one `*-<host>-skills.zip` archive per enabled
destination, including Pi, OpenClaw, goose, Crush, Cline, OpenHands, Hermes,
GitHub Copilot CLI, Gemini CLI, and Kilo CLI. It also creates seven supported
plugin/marketplace archives, and `host-packages.json` (`host-packages-v2`) with
SHA-256 digests, per-artifact offline `contract_id` validation (#27), and honest
`native_evidence_status=not-run` until host CLI revalidation is recorded.
Published `0.3.4` release assets remain historical nine-destination archives;
current `main` builds the registry-derived destination set. Replace `<version>`
below with the release version.

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
install-resume-skills quick-install all         # all user-global profiles (count derives from the registry)
install-resume-skills quick-install qwen --project "$PWD"
```

From a source checkout, use `pipx install .` instead. Both routes install the
same two CLI entry points. `quick-install` defaults to user-global roots; use
the lower-level transactional commands below for dry runs, explicit roots,
verification, backup replacement, or uninstall.

## Windows user install and shared Skill roots

When `pipx` is unavailable, install the wheel into Python's user site and ask
that interpreter for its own Scripts directory. Do not copy a version-specific
path such as `Python311\Scripts`; Python minor versions and Store/python.org
layouts differ.

```powershell
python -m pip install --user portable-resume
$scripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @($userPath -split ';' | Where-Object { $_ })
if ($parts -notcontains $scripts) {
  [Environment]::SetEnvironmentVariable('Path', (@($parts + $scripts) -join ';'), 'User')
}
```

Open a **new** PowerShell after updating the User PATH, then install and verify
the destination profiles you use:

```powershell
install-resume-skills quick-install claude
install-resume-skills verify --host claude --scope global
install-resume-skills quick-install cursor
install-resume-skills verify --host cursor --scope global
install-resume-skills quick-install codex
install-resume-skills verify --host codex --scope global
```

`quick-install all` preflights the requested profiles, groups aliases of the
same physical root, locks unique physical roots in deterministic order, and
leaves each root with a manifest representing its requested claims. When every
existing claim is included in an older-version coordinated upgrade, that new
generation is published once. The installer fails closed rather than publishing
mixed bundle versions. Verify each intended host separately because runtime
visibility through a junction is not the same as an ownership claim.

An intermediate symlink/junction spelling is rejected before installer control
state is created. A supported leaf Skill-root alias can participate in a shared
physical-root claim group. If `E_UNSAFE_PATH` occurs, pass `--root` using the
physical Skill directory and retry. If `E_VERIFY_MISMATCH` occurs, re-install
only after inspecting or repairing invalid ownership state; if the mismatch is
specifically a missing shared-root claim, re-install every intended host claim
together, then verify each host. Static
diagnostic hints deliberately contain no discovered paths; use `audit-host` for
bounded root discovery when needed.

Windows native mutation is supported, but the Windows release hard gate remains
the focused Claude/Cursor/Codex smoke in
[`WINDOWS_PRODUCTIZATION.md`](../WINDOWS_PRODUCTIZATION.md). It is not a full
306/306 Windows installed-runner or host-UI claim. Optional `doctor-path` and
continue-on-error behavior are not part of this workflow.

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

<!-- generated:install-hosts-table:begin (run scripts/render_docs.py --write) -->
| Host | Project root | Global root | Project install | Global install | Activation |
|---|---|---|---|---|---|
| Antigravity / agy (`antigravity`) | `<workspace>/.agents/skills/<name>/SKILL.md` | `~/.gemini/config/skills/<name>/SKILL.md` | `install-resume-skills install --host antigravity --scope project --project <PROJECT>` | `install-resume-skills install --host antigravity --scope global` | Mention the skill by name in natural language. `/skills` only lists skills; do not invent a `/resume-*` argv grammar. |
| Claude Code (`claude`) | `<project>/.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` | `install-resume-skills install --host claude --scope project --project <PROJECT>` | `install-resume-skills install --host claude --scope global` | Invoke `/resume-<source>` (or let the model auto-select by description). Any invocation tail is substituted into the skill prompt only; it is never process argv. |
| Cline (`cline`) | `<project>/.cline/skills/<name>/SKILL.md` | `~/.cline/skills/<name>/SKILL.md` | `install-resume-skills install --host cline --scope project --project <PROJECT>` | `install-resume-skills install --host cline --scope global` | Load resume-<source> from the Cline skills tree via use_skill or slash command. Recovered text is inert/untrusted handoff only. |
| Codex CLI / IDE (`codex`) | `<project>/.agents/skills/<name>/SKILL.md (CWD → repo root)` | `~/.agents/skills/<name>/SKILL.md` | `install-resume-skills install --host codex --scope project --project <PROJECT>` | `install-resume-skills install --host codex --scope global` | Invoke `$resume-<source>` followed by ordinary labeled text. There is no implicit skill-to-process argv binding. |
| Crush (`crush`) | `<project>/.crush/skills/<name>/SKILL.md` | `~/.config/crush/skills/<name>/SKILL.md` | `install-resume-skills install --host crush --scope project --project <PROJECT>` | `install-resume-skills install --host crush --scope global` | Load resume-<source> from the Crush skills tree. Recovered text is inert/untrusted handoff only. |
| Cursor Agent (`cursor`) | `<project>/.cursor/skills/<name>/SKILL.md` | `~/.cursor/skills/<name>/SKILL.md` | `install-resume-skills install --host cursor --scope project --project <PROJECT>` | `install-resume-skills install --host cursor --scope global` | Explicitly select `/resume-<source>` (or let the agent choose by description) and include labeled `resume_ref:` / `cwd:` in the same message. |
| Gemini CLI (`gemini`) | `<project>/.gemini/skills/<name>/SKILL.md` | `$GEMINI_CLI_HOME/.gemini/skills or ~/.gemini/skills/<name>/SKILL.md` | `install-resume-skills install --host gemini --scope project --project <PROJECT>` | `install-resume-skills install --host gemini --scope global` | Load resume-<source> from the Gemini CLI skills tree. Recovered text is inert/untrusted handoff only. Independent of Antigravity (agy) profile. |
| GitHub Copilot CLI (`github-copilot`) | `<project>/.github/skills/<name>/SKILL.md` | `$COPILOT_HOME/skills/<name>/SKILL.md (default ~/.copilot/skills/)` | `install-resume-skills install --host github-copilot --scope project --project <PROJECT>` | `install-resume-skills install --host github-copilot --scope global` | Load resume-<source> from the Copilot CLI skills tree via slash name / skills list. Recovered text is inert/untrusted handoff only. |
| goose (`goose`) | `<project>/.goose/skills/<name>/SKILL.md` | `~/.config/goose/skills/<name>/SKILL.md` | `install-resume-skills install --host goose --scope project --project <PROJECT>` | `install-resume-skills install --host goose --scope global` | Load resume-<source> from the goose skills tree. Recovered text is inert/untrusted handoff only. |
| Grok Build (`grok`) | `<repo>/.grok/skills/<name>/SKILL.md (CWD + repo root)` | `~/.grok/skills/<name>/SKILL.md` | `install-resume-skills install --host grok --scope project --project <PROJECT>` | `install-resume-skills install --host grok --scope global` | Invoke `/resume-<source>` with labeled payload text. Any `$ARGUMENTS` expansion is prompt substitution only. |
| Hermes Agent (`hermes`) | `<project>/.hermes/skills/<name>/SKILL.md` | `$HERMES_HOME/skills/<name>/SKILL.md (default ~/.hermes/skills/)` | `install-resume-skills install --host hermes --scope project --project <PROJECT>` | `install-resume-skills install --host hermes --scope global` | Load resume-<source> from the Hermes skills tree via slash command. Recovered text is inert/untrusted handoff only. |
| Kilo CLI (`kilo`) | `<project>/.kilocode/skills/<name>/SKILL.md` | `$KILO_CONFIG_DIR/skills or ~/.config/kilo/skills/<name>/SKILL.md` | `install-resume-skills install --host kilo --scope project --project <PROJECT>` | `install-resume-skills install --host kilo --scope global` | Load resume-<source> from the Kilo CLI skills tree (.kilocode/skills or ~/.config/kilo/skills). Recovered text is inert/untrusted handoff only. |
| Kimi Code CLI (`kimi`) | `<project>/.kimi-code/skills/<name>/SKILL.md` | `$KIMI_CODE_HOME/skills/<name>/SKILL.md (default ~/.kimi-code/skills)` | `install-resume-skills install --host kimi --scope project --project <PROJECT>` | `install-resume-skills install --host kimi --scope global` | Invoke `/skill:resume-<source>` or mention the skill by name; start a new session or `/reload` after installing a plugin. |
| OpenClaw (`openclaw`) | `<workspace>/skills/<name>/SKILL.md` | `~/.openclaw/skills/<name>/SKILL.md` | `install-resume-skills install --host openclaw --scope project --project <PROJECT>` | `install-resume-skills install --host openclaw --scope global` | Load resume-<source> from the workspace skills/ or ~/.openclaw/skills tree. Recovered text is inert/untrusted handoff only. |
| OpenCode (`opencode`) | `<project>/.opencode/skills/<name>/SKILL.md` | `~/.config/opencode/skills/<name>/SKILL.md` | `install-resume-skills install --host opencode --scope project --project <PROJECT>` | `install-resume-skills install --host opencode --scope global` | Ask the model to use the skill by name so it can call native skill loading. Optional OpenCode custom commands are separate and not required for this package. |
| OpenHands (`openhands`) | `<project>/.agents/skills/<name>/SKILL.md` | `~/.openhands/skills/<name>/SKILL.md` | `install-resume-skills install --host openhands --scope project --project <PROJECT>` | `install-resume-skills install --host openhands --scope global` | Load resume-<source> from the OpenHands skills tree. Recovered text is inert/untrusted handoff only. |
| Pi agent (`pi`) | `<project>/.pi/skills/<name>/SKILL.md` | `~/.pi/agent/skills/<name>/SKILL.md` | `install-resume-skills install --host pi --scope project --project <PROJECT>` | `install-resume-skills install --host pi --scope global` | Invoke `/skill:resume-<source>` (Pi progressive disclosure). Any invocation tail is substituted into the skill prompt only; it is never process argv. |
| Qwen Code (`qwen`) | `<project>/.qwen/skills/<name>/SKILL.md` | `~/.qwen/skills/<name>/SKILL.md` | `install-resume-skills install --host qwen --scope project --project <PROJECT>` | `install-resume-skills install --host qwen --scope global` | Invoke `/resume-<source>` or choose it from `/skills`; the model may also select a skill from its description. |
<!-- generated:install-hosts-table:end (run scripts/render_docs.py --write) -->

For direct archives, extract the archive contents into the selected Skill root.
Each archive contains every enabled `resume-<source>` Skill from the registry.

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

## Upgrading and resolving E_INSTALL_SHADOW

After a package upgrade, `install-resume-skills quick-install all` (or a lower-level
`install`) can fail with exit code **6** and empty stdout when a
**higher-precedence** discovery root already holds a divergent Portable Resume
Skill (for example an older project-scope install while you target user-global).
Stderr is a single `portable-resume/diagnostic-v1` JSON line with code
`E_INSTALL_SHADOW` and a static remediation `hint`.

1. **Diagnose** the conflicting root (read-only):

```bash
install-resume-skills audit-host --host <key> --scope <scope> [--project <dir>]
```

Use the host key and scope you intended to install (for example `grok` /
`project`, or `cursor` / `global`). Add `--project` when scanning project roots.

2. **Resolve** by removing the stale claim, or by installing to an explicit root:

```bash
# Uninstall the stale higher-precedence claim, then re-install
install-resume-skills uninstall --host <key> --scope <scope> [--project <dir>] [--home <dir>]
install-resume-skills install --host <key> --scope <scope> [--project <dir>] [--home <dir>]

# Or install to an explicit project / root so discovery order no longer blocks
install-resume-skills quick-install <profile> --project <other-dir>
install-resume-skills install --host <key> --scope project --project <dir>
```

3. **Failure shape**: exit **6**, **empty stdout**, structured diagnostic on
stderr only. Paths and user data never appear in the diagnostic; use
`audit-host` to locate the root on disk.

## Evidence boundary

Current `main` claims registry-derived **17×18=306** packaging and installed-runner
cells. Published `0.3.4`
remains historical **9×9=81**. Historical `0.3.2` / `0.3.3` evidence covered
**64/64** cells. Exact `0.3.2` local package installation passed on all seven
supported native plugin/extension surfaces, including Cursor. Host-native
headless Skill invocation and public marketplace picker flows for fresh
OpenClaw/Pi native UI remain **not-run**. Versions, commands, and archive
digests are recorded in [`host-ui-smoke.md`](host-ui-smoke.md). Other visual
Skill pickers and vendor-curated directory listings remain separate unclaimed
gates.
