# Audit: `docs/host-support.md` vs official host skill docs (2026-07-20)

**Verdict: NEEDS UPDATES**

**Scope (read-only):**  
`docs/host-support.md`、`src/portable_resume/install/catalog.py`、`.omx/context/host-profile-*.md`（本機 disk 存在、可能 gitignore）、以及 2026-07-20 可取的官方/ upstream 文件。  
**未執行：** 六 host live UI activation smoke（與公開文件一致標為 `not-run`）。

---

## Executive summary

`host-support.md` 在 **packaging roots 主路徑**、**portable frontmatter 只保留 `name`+`description`**、以及 **live smoke 全列 `not-run`** 這三點上整體誠實，且與 `catalog.py` 一致。  
但公開表把部分 **activation 文法寫成凍結定論**，且有幾處 **官方文檔 / 本機 probe 張力未被寫進公開 matrix**：

1. **OpenCode**：官方寫 native `.opencode/skills`；本機 1.15.10 `opencode debug skill --pure` **未發現** 該 native root，只證明 `.claude`/`.agents` 相容根。
2. **Cursor**：官方一等公民同時含 `.agents/skills` **與** `.cursor/skills`；公開表只列 `.cursor/skills`（可作為 packaging 選擇，但應標成「選定 primary」，不是「唯一官方 root」）。
3. **Claude 列** 的 packaging 備註含 `installed runtime handoff OK`，容易被讀成 live UI 已驗證（實際上 live 仍 `not-run`）。
4. **Antigravity 全域 root** 選 `~/.gemini/config/skills` 有官方與第三方交叉驗證支撐，但 **AGY / AGY CLI / AGY IDE 另有產品專屬全域路徑**；公開表未提示 multi-flavor 風險。
5. **Grok `$ARGUMENTS`**：官方 product docs 證實 `/skill-name` 與 `.grok/skills`，但 **`$ARGUMENTS` 置換語意主要來自 source/local bundle 證據**，公開表未區分「官方 UI 文法」vs「source-verified prompt 置換」。

因此：**不是全面 OVERCLAIMING**（live 誠實、argv 多半有防過信措辭），也 **不是 WELL GROUNDED 到可凍結不再改** —— 需要把 evidence 層級、alternate roots、與 probe 衝突寫進公開 docs。

---

## Method

| Source | Role |
|---|---|
| `docs/host-support.md` | 被審公開契約 |
| `src/portable_resume/install/catalog.py` | 實作 roots / activation_help 權威 |
| `.omx/context/host-profile-official-evidence-20260720.md` | 規劃期官方證據彙整 |
| `.omx/context/host-profile-local-evidence-20260720.md` | 本機版本 probe（auth 多半 blocked） |
| Live official docs (2026-07-20 fetch) | Claude Code skills、Codex build-skills、Cursor skills、OpenCode skills、Antigravity/codelab、Grok skills-plugins |
| Independent AGY path survey (atamel.dev, 2026-07) | 交叉驗證 Antigravity multi-flavor 全域路徑 |

**Live smoke honesty:** 本 audit **同樣未跑** host UI picker / NL activation e2e。任何「host 真的會載入並執行 skill」的 claim 仍屬未驗證。

---

## Claim matrix vs reality

| Host | `host-support.md` project root | Official primary roots | Local probe roots | Activation claim | Official/local activation | Public claim risk |
|---|---|---|---|---|---|---|
| Claude | `.claude/skills` | `.claude/skills` + `~/.claude/skills` | 同左（debug discovery） | `/resume-<source>`; `$ARGUMENTS` prompt-only | `/skill-name [tail]`; `$ARGUMENTS`/`$N` **prompt 置換** 官方明文 | **Low**（措辭需避免 handoff=live） |
| Codex | `.agents/skills` | `.agents/skills`（CWD→repo root）+ `~/.agents/skills`；另 admin `/etc/codex/skills` | 另見 `.codex/skills` | `$resume-<source>` + labels；無 implicit argv | CLI/IDE：`$skill`；`/skills` 列表；**無** `$ARGUMENTS` argv API | **Low–Med**（可補 alternate `.codex/skills`） |
| Cursor | `.cursor/skills` only | **`.agents/skills` + `.cursor/skills`**（project/global 皆雙 root）；相容 `.claude`/`.codex` | 同官方 + 相容根 | explicit `/resume-<source>` + labels | `/skill-name` 可手動選；docs **未**定義 tail→argv | **Med**（primary 不完整；activation 可接受） |
| OpenCode | `.opencode/skills` + `~/.config/opencode/skills` | 官方 **native 同左** + 相容 `.claude`/`.agents` | **probe 未回傳 native**；只證明相容根 | model/native skill selection | `skill({name})`；無 user `/skill-name` skill 文法 | **Med–High**（root 證據衝突未公開） |
| Antigravity | `.agents/skills` + `~/.gemini/config/skills` | workspace `.agents/skills`；global 官方表為 `~/.gemini/config/skills`；legacy `.agent/skills` | binary 亦見多 alias；無 e2e | name mention；`/skills` lists only | codelab：NL 觸發 + `/skills` 列表；**不承諾** `/skill-name argv` | **Med**（global 選對，但 multi-flavor 未寫） |
| Grok | `.grok/skills` + `~/.grok/skills` | 官方：`./.grok/skills`、`~/.grok/skills`；另相容/agents/plugins | 同左 + 相容 vendor roots | `/resume-<source>`; `$ARGUMENTS` prompt-only | 官方：`/<skill-name>` slash；`$ARGUMENTS` **source-high** | **Low–Med**（應標 `$ARGUMENTS` 證據層級） |

`catalog.py` 與 `host-support.md` 的 profile id / project_rel / global_rel **一致**，無 catalog–docs 漂移。

---

## Per-host detail

### 1. Claude Code — confidence **High**

**Public claims**

- Project: `<project>/.claude/skills`
- Global: `~/.claude/skills`
- Activation: `/resume-<source> ...`; `$ARGUMENTS` prompt-only
- Packaging: `verified-filesystem` + 備註 `installed runtime handoff OK`
- Live: `not-run` (host UI picker/NL)

**Official (2026-07-20)** — [Claude Code skills](https://code.claude.com/docs/en/skills)

- Personal `~/.claude/skills/<name>/SKILL.md`、project `.claude/skills/<name>/SKILL.md` 明文。
- 呼叫：`/skill-name`；亦可 model auto-load by description。
- `$ARGUMENTS`、`$ARGUMENTS[N]`、`$N` 為 **skill content 字串置換**；無 process argv 契約。與「prompt-only」一致且強。

**Local**

- Claude Code `2.1.215`；isolated discovery 載入 user/project skill roots；auth 擋住 e2e 擴張捕捉。

**Flags**

| Severity | Issue |
|---|---|
| MINOR / wording | packaging 欄 `installed runtime handoff OK` 與 live `not-run` 並列，易被讀成「host 已 live 驗證」。應改成「reader/request-file 路徑 filesystem+unit 證明；UI activation 未跑」。 |
| Note | 官方還有 nested monorepo skills、plugin namespace、commands 合併等；對 V1 packaging 非 blocker，但「唯一 root」表述已足夠。 |

**Recommended doc edit**

- 維持 roots / `/skill-name` / `$ARGUMENTS` prompt-only。
- 拆分 packaging evidence 與「runtime handoff」措辭；明確 handoff ≠ live UI smoke。

---

### 2. Codex CLI — confidence **High**

**Public claims**

- Project/global: `.agents/skills` / `~/.agents/skills`
- Activation: `$resume-<source>` + labels；no implicit argv
- Live: `not-run`

**Official** — Codex *Build skills*（`developers.openai.com/codex/skills` → 目前導向 ChatGPT Learn *Build skills*）

- REPO：`$CWD/.agents/skills` 向上到 `$REPO_ROOT/.agents/skills`
- USER：`$HOME/.agents/skills`
- ADMIN：`/etc/codex/skills`
- Explicit：`$skill` / Skills UI；implicit by description
- 無 `$ARGUMENTS` skill argv API；參數為 ordinary request text

**Local**

- `codex-cli 0.144.6`；另發現 **`.codex/skills`**（project/home），公開表未列。

**Flags**

| Severity | Issue |
|---|---|
| MINOR | 未記載 `.codex/skills` alternate / compatibility root。對「選 `.agents/skills` 當 packaging primary」合理，但應一句話標「primary not exclusive」。 |
| OK | `$` activation + no implicit argv 與官方一致；`catalog.py` 文案正確。 |

**Recommended doc edit**

- 加 footnote：Codex 亦可能掃 `.codex/skills`（local 0.144.6）；本產品安裝 primary 仍為 `.agents/skills`。
- Shared-root 與 Antigravity 衝突 note 保留（正確且重要）。

---

### 3. Cursor — confidence **Med**（roots 選擇）/ **Med–High**（activation 保守）

**Public claims**

- Only `.cursor/skills` / `~/.cursor/skills`
- Activation: explicit `/resume-<source>` + labels
- Live: `not-run`

**Official** — [Cursor skills](https://cursor.com/docs/skills)

| Location | Scope |
|---|---|
| `.agents/skills/` | Project |
| `.cursor/skills/` | Project |
| `~/.agents/skills/` | Global |
| `~/.cursor/skills/` | Global |

- 另相容：`.claude/skills`、`.codex/skills`（project/global）
- Manual invoke：Agent chat 打 `/` 搜 skill 名
- Docs **不**定義 invocation-tail placeholder / argv binding；agent 讀指令後 model-mediated 執行

**Local**

- Cursor CLI `2026.07.16-899851b` JS 顯示 `$ARGUMENTS` / `$1..$99` **存在於 shipped code**，但官方 docs 未承諾；`catalog.py` 正確拒絕依賴該 channel。

**Flags**

| Severity | Issue |
|---|---|
| **MAJOR (docs completeness)** | 公開表把 project/global 寫成僅 `.cursor/skills`，**低報官方一等公民 `.agents/skills`**。若讀者以為 Cursor 只吃 `.cursor`，在已有 `.agents/skills` 的 monorepo 會誤判衝突/覆蓋語意。 |
| OK | activation「explicit `/` + labels」與「不要依賴 argv」——與官方負面證據一致；比 local JS 擴張行為更保守，方向正確。 |

**Recommended doc edit**

```text
cursor-v1 packaging primary: .cursor/skills (+ ~/.cursor/skills)
also official first-class: .agents/skills (+ ~/.agents/skills)
compat (not installed by us): .claude/skills, .codex/skills
activation: prefer explicit /resume-* + labeled payload; do not claim $ARGUMENTS
```

---

### 4. OpenCode — confidence **Med**（整體）/ **Low–Med**（native root 可發現性）

**Public claims**

- Project: `.opencode/skills`
- Global: `~/.config/opencode/skills`
- Activation: model/native skill selection + labels
- Packaging: `verified-filesystem`
- Live: `not-run`

**Official** — [OpenCode Agent Skills](https://opencode.ai/docs/skills/)（頁面標 last updated 2026-07-20）

- Native：`.opencode/skills`、`~/.config/opencode/skills`
- Compat：`.claude/skills`、`.agents/skills`（project + global）
- Frontmatter：僅 `name`/`description` + optional `license`/`compatibility`/`metadata`
- Activation：`skill({ name: "..." })`；**無**穩定 user `/skill-name [tail]` skill 文法
- Custom commands 是另一 surface（可有 `$ARGUMENTS`）——與 skill 分離（`catalog.py` 已正確區分）

**Local (critical tension)**

- OpenCode `1.15.10`：`opencode debug skill --pure` **實際回傳** project/home 的 `.claude/skills` 與 `.agents/skills`。
- **未回傳** project `.opencode/skill(s)` 或 global `.config/opencode/skill(s)` sentinels。
- 與 shipped help / 官方 docs 衝突 → local evidence 檔已標 medium-high 並要求 version-specific recheck。

**Flags**

| Severity | Issue |
|---|---|
| **MAJOR** | 公開 `host-support.md` 把 native OpenCode roots 標成與其他 host 同級的 `verified-filesystem` packaging 定論，**未揭露「官方 root ≠ 本機 1.15.10 debug discovery」**。filesystem install 可以寫進該路徑，但「host 會發現」尚未被該版本 probe 證明。 |
| MINOR | Activation 文案（model/native selection）與官方一致，屬 good。 |

**Recommended doc edit**

- Packaging root 可續用官方 native 路徑，但 evidence 改：
  - `verified-filesystem` = installer 寫入/校驗路徑
  - `discovery` = `partial` / `conflict-with-local-1.15.10` until re-probe or compat fallback install
- 考慮文件註記：若 native discovery 失敗，相容安裝到 `.agents/skills` 或 `.claude/skills` 的取捨（需處理與 Codex/Antigravity 共享根衝突）。

---

### 5. Antigravity / `agy` — confidence **Med–High**（選中的 roots）/ **Med**（activation 負面主張）

**Public claims**

- Project: `.agents/skills`
- Global: `~/.gemini/config/skills`
- Activation: name mention；`/skills` lists only
- Live: `not-run`

**Official + codelab**

- [antigravity.google/docs/skills](https://antigravity.google/docs/skills)（crawl/摘要）：workspace `.agents/skills`；global `~/.gemini/config/skills`；legacy `.agent/skills`
- Codelab：建在 `.agents/skills/...`；`/skills` 列表；NL「What is my favorite color?」觸發 skill — **不是** `/my-favorite-things argv`

**Cross-check (third-party experiment, 2026-07)**

- `~/.gemini/config/skills` 是 **AGY / AGY CLI / AGY IDE 唯一共同全域**
- 產品專屬全域仍存在，例如：
  - AGY：`~/.gemini/antigravity/skills`
  - AGY CLI：`~/.gemini/antigravity-cli/skills`（CLI docs 曾寫此為 global）
  - 另見 `~/.gemini/skills` 等
- 選 `~/.gemini/config/skills` 作為 portable global **正確且偏安全**

**Local**

- `agy 1.1.4` binary strings：workspace walk `.agents`/`.agent`/`_agents`/`_agent`；global `~/.gemini/config/skills`；**無** 可證明的 `$ARGUMENTS` channel；named slash 可能存在但 **未 e2e**。

**Flags**

| Severity | Issue |
|---|---|
| MINOR–MAJOR (clarity) | 「`/skills` lists only」是 **合理保守負面主張**，但證據是「官方 example 不承諾 + 本機未 e2e」，不是「二進位證明 slash 執行不存在」。應標 `negative-claim: medium`。 |
| MINOR | 應註記 multi-flavor 全域路徑分歧，避免使用者把 CLI-only path 當全產品真相。 |
| OK | 與 Codex 共享 project `.agents/skills` 的 conflict note 正確。 |

**Recommended doc edit**

```text
antigravity-v1:
  project: .agents/skills (shared with Codex; installer conflict applies)
  global: ~/.gemini/config/skills  # cross-flavor intersection
  note: AGY/CLI/IDE may also read product-specific globals; we do not install there
  activation: NL name mention; /skills = list; no claimed /resume-* argv grammar
  evidence: roots high; slash-exec negative claim medium; live not-run
```

---

### 6. Grok Build — confidence **High**（roots + slash）/ **Med–High**（`$ARGUMENTS` 細節）

**Public claims**

- `.grok/skills` / `~/.grok/skills`
- `/resume-<source> ...`; `$ARGUMENTS` prompt-only
- Live: `not-run`

**Official** — [Skills, Plugins & Marketplaces](https://docs.x.ai/build/features/skills-plugins-marketplaces)

- Discover: `./.grok/skills/`（walk to repo root）、`~/.grok/skills/`、plugins、config extra paths
- User-invocable skills appear as slash commands: `/<skill-name>`
- Claude Code / `~/.agents/skills` 相容性有寫
- **公開此頁未展開 `$ARGUMENTS` / `$N` 置換表**

**Local / source**

- `grok 0.2.106` + grok-build source：`$ARGUMENTS`、`$ARGUMENTS[N]`、`$N`、fallback `**ARGUMENTS:**` 均為 **prompt 內置換**，非 process argv — 與 public claim 方向一致且更強。

**Flags**

| Severity | Issue |
|---|---|
| MINOR | 公開表把 `$ARGUMENTS` 與 Claude 同句式並列；對 Grok 應註「source/local verified; product docs confirm slash roots」。 |
| OK | roots 與 `/skill-name` 與官方一致；未假稱 live。 |

**Recommended doc edit**

- 維持 packaging roots。
- Activation 拆兩層：  
  1) 官方：`/skill-name`  
  2) 置換：`$ARGUMENTS` = prompt-only（source-verified）

---

## Cross-cutting findings

### A. Live smoke honesty — **GOOD**

所有六列 Live smoke = `not-run`；`docs/evidence-summary.md` / `docs/STATUS.md` 亦寫 live UI 未 claim。  
**本 audit 再次確認：live UI activation 未跑。**  
不要把 packaging `verified-filesystem` 升級成 `verified-live`。

### B. 「Activation contracts frozen」措辭 — **SLIGHTLY OVERCONFIDENT**

對 Claude / Codex / Grok 凍結合理。  
對 **Cursor tail 語意、OpenCode user grammar、Antigravity slash-exec**，官方 evidence 檔自己也列為 residual gates。公開 `host-support.md` 第一句「activation contracts frozen」應降級為：

> packaging primary roots frozen; activation **guidance** frozen with per-host evidence levels; live unproven.

### C. Portable frontmatter `name`+`description` only — **WELL GROUNDED**

與 Agent Skills baseline 及各 host「最小可攜」策略一致。不把 host-only keys 寫進 portable core 是正確的。

### D. Shared Codex ↔ Antigravity project root — **WELL GROUNDED**

`.agents/skills` 衝突與 `E_INSTALL_CONFLICT` 說明應保留。

### E. `catalog.py` vs docs — **ALIGNED**

| Host | catalog project_rel | catalog global_rel | host-support |
|---|---|---|---|
| claude | `.claude/skills` | `.claude/skills` | match |
| codex | `.agents/skills` | `.agents/skills` | match |
| cursor | `.cursor/skills` | `.cursor/skills` | match |
| opencode | `.opencode/skills` | `.config/opencode/skills` | match |
| antigravity | `.agents/skills` | `.gemini/config/skills` | match |
| grok | `.grok/skills` | `.grok/skills` | match |

Activation help 字串比表格更完整且更謹慎（尤其 Cursor/OpenCode/Antigravity）；**表格過度壓縮造成部分過信**。

---

## Confidence scoreboard

| Host | Roots | Activation grammar | Argv / parameter channel | Live UI | Overall for public docs |
|---|---|---|---|---|---|
| Claude Code | **High** | **High** | **High** (prompt-only) | **not-run** | **High** |
| Codex CLI | **High** (primary) | **High** (`$skill`) | **High** (no argv) | **not-run** | **High** |
| Cursor | **Med** (incomplete primary list) | **Med–High** | **Med–High** (docs neg / code pos) | **not-run** | **Med** |
| OpenCode | **Med** (docs vs probe) | **High** (skill tool) | **High** (no skill argv) | **not-run** | **Med** |
| Antigravity/agy | **High** (chosen roots) | **Med** | **Med–High** (no argv claimed) | **not-run** | **Med–High** |
| Grok Build | **High** | **High** (slash) | **Med–High** (`$ARGUMENTS` source) | **not-run** | **High** |

---

## Recommended doc edits (actionable)

優先寫進 `docs/host-support.md`（不需動 product code 即可改善誠實度）：

1. **改 status 句**  
   - From: packaging roots and activation contracts frozen  
   - To: packaging **primary** roots frozen 2026-07-20; activation is **documented guidance** with evidence levels; live UI = not-run.

2. **OpenCode 列**  
   - 加 discovery caveat：official native roots documented; local OpenCode 1.15.10 pure-debug did not list them; discovery = partial until re-verified.  
   - packaging `verified-filesystem` 限縮為「installer path layout」，不要暗示 host discovery。

3. **Cursor 列**  
   - Primary packaging: `.cursor/skills`  
   - Also official: `.agents/skills`  
   - Compat: `.claude`/`.codex`（not installed by default）

4. **Claude 列 packaging note**  
   - 刪除/改寫 `installed runtime handoff OK` → 明確「request-file runner / unit handoff」vs「host UI activation not-run」。

5. **Antigravity 列**  
   - 加 multi-flavor global footnote；維持 `~/.gemini/config/skills`  
   - `/skills lists only` 改為「documented/list UI; named slash execution not live-proven」

6. **Grok 列**  
   - 分拆：official slash + roots；`$ARGUMENTS` = source-verified prompt substitution

7. **Codex 列（optional）**  
   - footnote：local also saw `.codex/skills`; packaging stays `.agents/skills`

8. **Evidence pointer**  
   - 維持指向 `.omx/context/host-profile-official-evidence-20260720.md`；若 `.omx` 不進公開 repo，應在 `docs/` 放精簡 public digest（或本 audit）以免 orphan pointer。

9. **不要** 把任何 host 的 Live 欄改成 `verified-live` / `partial` live，除非真的跑過 request→handoff UI smoke。

---

## What would change the verdict

| To reach | Need |
|---|---|
| **WELL GROUNDED** | 套用上表 doc edits；OpenCode 對 1.15.10+ 重跑 discovery 並寫入結果；Cursor 雙 root 寫清 |
| **OVERCLAIMING** | 若未來去掉 live `not-run`、或把 OpenCode/Cursor 寫成「唯一且已 live 驗證」卻無證據 |
| Stay **NEEDS UPDATES** | 維持現狀表格不改（現況） |

---

## Live smoke not-run honesty (explicit)

| Cell class | Status in repo | Status in this audit |
|---|---|---|
| 36 packaging install/verify filesystem | claimed verified-filesystem (macOS) | **not re-executed here**; assumed from `docs/evidence-summary.md` |
| 36 live host UI activation | **not-run** | **not-run**（確認未跑） |
| Linux peer OS | not claimed | not claimed |

---

## Verdict justification

- **Roots 主路徑**多數有 2026-07-20 官方文件支撐，且 `catalog.py` 一致。  
- **Live 誠實** 防止整體掉進 OVERCLAIMING。  
- 但公開 matrix **壓縮掉** OpenCode discovery 衝突、Cursor 雙 primary、以及數個 negative activation claims 的證據層級，使得「frozen activation contracts」**略過硬**。  

→ **NEEDS UPDATES**（優先修文件措辭與 caveats；不必因此否定 packaging 架構）。

---

## Sources consulted (2026-07-20)

- Claude Code skills: https://code.claude.com/docs/en/skills  
- Codex build skills: https://developers.openai.com/codex/skills/ (redirects to ChatGPT Learn build-skills)  
- Cursor skills: https://cursor.com/docs/skills  
- OpenCode skills: https://opencode.ai/docs/skills/  
- Antigravity skills: https://antigravity.google/docs/skills  
- Antigravity CLI codelab: https://codelabs.developers.google.com/antigravity/how-to-create-agent-skills-for-antigravity-cli  
- Grok skills/plugins: https://docs.x.ai/build/features/skills-plugins-marketplaces  
- Local: `.omx/context/host-profile-official-evidence-20260720.md`, `host-profile-local-evidence-20260720.md`  
- Third-party AGY path survey: https://atamel.dev/posts/2026/07-01_where_agy_agent_skills/

---

*Audit type: read-only research. No product code changes. Report only: `docs/audit-host-docs-evidence.md`.*
