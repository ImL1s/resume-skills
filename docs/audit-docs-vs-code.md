# 文件 vs 程式碼／測試稽核報告

**日期：** 2026-07-20  
**範圍：** 唯讀比對 public docs 與 `src/`、`tests/`、`scripts/`、`.github/workflows/ci.yml`  
**原則：** 不信任文件單方敘述；以實際程式與測試為準。

---

## Verdict: **MOSTLY ACCURATE WITH FIXES**

核心產品敘事（六來源 × 六宿主、stdlib-only、packaging 36 / live 0、不宣稱 live UI／雙 OS release、clean-room 有界 attestation、CI 無 CD）與程式碼**大致一致且誠實**。  
但公開 clone **無法使用**的 `.omx/` 路徑仍被寫成官方 evidence 指標，且 open-source readiness plan 已勾選「移除 `.omx/` 必要連結」卻未清乾淨——這會讓外部讀者誤以為有可追蹤的官方 evidence 檔。

不構成「產品行為假宣稱」等級的 MISLEADING（例如並未假稱 live UI 已過），但 **public docs 的可驗證性有明確缺口**，應修。

---

## Critical inaccuracies（錯命令／假宣稱／公開不可用連結）

### C1. 公開 clone 死鏈：`.omx/context/...` 被當官方 evidence

| 位置 | 內容 | 實際 |
|---|---|---|
| `docs/host-support.md:33` | `See .omx/context/host-profile-official-evidence-20260720.md for URLs, versions...` | `.omx/` 在 `.gitignore:12` 整目錄忽略，**不在 git tree**，public clone 打不開 |
| `docs/source-formats.md:22` | 寫「tracked public evidence under `.omx/context/`」 | **不 tracked、不 public**；與「tracked public」字面矛盾 |

對照：

- `docs/superpowers/plans/2026-07-20-open-source-readiness.md:347` 已勾選：  
  *no `.omc/research/`, no `.omx/` required links for public readers*
- `tests/unit/test_provenance_honesty.py:27-30` 只禁止 README/STATUS/host-support 含 `.omc/research/`，**未檢查 `.omx/`**，故 C1 漏網

**為何 critical：** 外部讀者按 docs 找「official evidence」會 404；且把 gitignored 本地檔寫成 tracked public evidence 是文件層級的假宣稱。

**建議修復：** 刪除或改寫為「local planning notes (not shipped)」；官方 URL 若需保留，應改寫進已 ship 的 `docs/`（例如 `host-support.md` / `evidence-summary.md`）或明確標 **optional local only**。

---

## Important mismatches

### I1. Linux / dual-OS 措辭與現有 Ubuntu CI 不完全對齊

| 文件說法 | 實際 |
|---|---|
| `docs/STATUS.md:21` Linux peer clean runner (AC-18) = **not-run** | `.github/workflows/ci.yml` 已在 **ubuntu-latest + macos-latest** 跑 compileall / secrets / unittest / self-check / matrix / self_verify |
| `docs/host-support.md:40` Linux gate「not claimed unless artifacts archived」 | GH Actions run log 本身就是可稽核 artifact；但專案刻意未把 CI 綠燈升格為 dual-OS **release claim** |
| README / evidence-summary「dual-OS release completeness not claimed」 | 與程式/測試誠實意圖一致 |

**判定：** 不宣稱 dual-OS release 是正確的；但 STATUS 用 **not-run** 描述 Linux 會讓人以為「完全沒在 Linux 跑過」，與 public CI 衝突。

**建議：** STATUS 改為例如  
`CI runs on Ubuntu (not elevated to dual-OS release claim; no archived peer-OS release packet)`  
保留「full V1 release complete = no」。

### I2. Fixture `provenance_ref` 片段錨點多半不存在

`tests/helpers/fixture_manifest.py:92-94` 只要求字串以 `docs/source-formats.md#` 開頭，**不驗證 heading 是否存在**。

實際 fixture 例：

- `docs/source-formats.md#claude-claude-jsonl-v1`
- `docs/source-formats.md#codex-codex-state-sqlite-v1`
- `docs/source-formats.md#cursor-cursor-cli-chat-v1`

`docs/source-formats.md` **沒有**對應 HTML heading（表格列不會產生這些 anchor）。  
僅頂層標題可解為 `#source-format-evidence-registry`；`#foundation-only` 只以行內 code 出現，也不是 heading id。

**建議：** 在 `source-formats.md` 為各 format 加 `###` 錨點，或統一改 fixture `provenance_ref` 到存在的 section，並加測試驗證 fragment。

### I3. `opencode-export-file-v1` 有實作、文件表格未列 ID

- Code：`src/portable_resume/adapters/opencode.py:35-37`  
  `SQLITE_FORMAT` / `FILE_FORMAT` / `EXPORT_PROVIDER = "opencode-export-file-v1"`
- Docs 表格：`opencode-file-store-v1`, `opencode-sqlite-v1`；limitation 寫「export provider is separate」

**判定：** 非假宣稱，但 registry 不完整。建議在 Format ID 欄或 limitation 明確寫出 `opencode-export-file-v1`。

### I4. Python 版本敘述偏弱／與 CI 矩陣不一致

| 宣稱 | 實際 |
|---|---|
| README / CONTRIBUTING：`Python 3.11+ recommended` | 無 `requires-python` / pyproject 強制 |
| CI：`python-version: ["3.12"]` only | **未測 3.11** |
| 語法 | `list[str]`、`str \| None`、`@dataclass(..., slots=True)` → 至少 3.10+ 可跑 |

**建議：** 寫明「CI 驗證 3.12；3.11 應可用但未在 CI 矩陣」；若堅持 3.11+，CI 加 3.11 job。

### I5. 誠實性測試未覆蓋 `.omx/` 死鏈（測試缺口，非產品 bug）

- 有：禁 `.omc/research/` 出現在 README/STATUS/host-support  
- 無：禁 `.omx/` 必要連結  
→ 與 open-source plan Step 4 完成勾選不一致

### I6. `docs/source-formats.md`「G002 status」欄位未定義

表格欄名 `G002 status`，public docs 未解釋 G002 是什麼 gate。外部讀者無法解讀。  
建議改為 `Adapter status` 或加一小節定義。

---

## 已核對為準確的項目（正面）

### 1. 六來源 / 六宿主 / 36 packaging / live 0

| 宣稱 | 證據 |
|---|---|
| 六 source skills | `diagnostics.py` / `model.py`：`SOURCE_KEYS` = claude, codex, cursor, opencode, antigravity, grok |
| 六 adapters | `src/portable_resume/adapters/{claude,codex,cursor,opencode,antigravity,grok}.py` 皆存在 |
| 六 host profiles | `install/catalog.py:HOST_PROFILES` 六鍵 |
| packaging 36 | `matrix_cells()` = 6×6；`matrix_report()["cell_count"]` / tests assert 36 |
| live 0 | `transaction.py:matrix_report` 每格 `live_supported: False`，`live_cells_supported: 0`（硬編碼 by design） |

README maturity label「Packaging 36/36 · Live UI 0」與 code **一致**。

### 2. `docs/host-support.md` roots / activation vs `HOST_PROFILES`

| Profile | Project / Global root | 與 catalog.py | 結論 |
|---|---|---|---|
| claude-v1 | `.claude/skills` / `.claude/skills` | 一致 | OK |
| codex-v1 | `.agents/skills` / `.agents/skills` | 一致 | OK |
| cursor-v1 | `.cursor/skills` / `.cursor/skills` | 一致 | OK |
| opencode-v1 | `.opencode/skills` / `.config/opencode/skills` | 一致 | OK |
| antigravity-v1 | `.agents/skills` / `.gemini/config/skills` | 一致 | OK |
| grok-v1 | `.grok/skills` / `.grok/skills` | 一致 | OK |

Activation 摘要（slash / `$` / name-mention / `$ARGUMENTS` prompt-only）與 `activation_help` / `arguments_note` **語意一致**（catalog 對 claude 另提 model auto-select，docs 略簡——屬 minor）。

Shared-root / `E_INSTALL_CONFLICT` 敘述與 installer 行為一致。

### 3. `docs/source-formats.md` Format ID vs adapters

| Source | Docs Format ID(s) | Code constants | 一致？ |
|---|---|---|---|
| Claude | `claude-jsonl-v1` | `claude.FORMAT_ID` | ✅ |
| Codex | `codex-rollout-jsonl-v1`, `codex-state-sqlite-v1`, optional `codex-rollout-zstd-v1` | `ROLLOUT_FORMAT` / `SQLITE_FORMAT` / `ZSTD_FORMAT` | ✅ |
| Cursor | `cursor-cli-chat-v1`, `cursor-desktop-vscdb-v1` | `CLI_FORMAT` / `DESKTOP_FORMAT` | ✅ |
| OpenCode | `opencode-file-store-v1`, `opencode-sqlite-v1` | `FILE_FORMAT` / `SQLITE_FORMAT`（+ 未列表的 export） | ✅ 主 ID；export 見 I3 |
| Antigravity | `antigravity-transcript-jsonl-v1` | `FORMAT_ID` | ✅ |
| Grok | `grok-updates-jsonl-v1` | `FORMAT_ID` | ✅ |

Fixtures 的 `format_id` 與此表一致（46 個 fixture.json 抽樣全過）。

### 4. README 命令 / install paths / self_verify / CI

| 宣稱 | 實際 |
|---|---|
| `scripts/portable-resume` / `scripts/install-resume-skills` | 存在；皆 inject `SRC` 進 `sys.path` |
| `self-check --json` | `reader.self_check`；六 adapters + matrix 36 |
| `matrix --json` | `install.cli` → `matrix_report()` |
| fixture list/show 路徑 | 與 `self_verify.py` 使用同一 claude fixture |
| install `--host claude --scope project --project --dry-run/--json` | `install/cli.py` flags 相符 |
| `run_reader.py --request-file --format handoff` + hard-bind source | `run_reader.py.tmpl` 剝除 host `--expected-source` 後強制 skill source |
| `python3 scripts/self_verify.py` → `OVERALL_SELF_VERIFY PASS/FAIL` | `scripts/self_verify.py:89` |
| `check_secrets.py` | 存在；CI 與 CONTRIBUTING 有呼叫 |
| CI Ubuntu + macOS；無 CD/PyPI | `ci.yml` 僅 test job；repo 無 publish workflow |
| stdlib only + optional host `zstd` | 無第三方 runtime dep；codex `TRUSTED_ZSTD_PATHS` 固定路徑、no shell |

註：README 示例帶 `PYTHONPATH=src` **多餘但無害**（wrapper 已 self-inject）。

### 5. STATUS done / not-done vs tree

| STATUS 項 | 存在？ |
|---|---|
| Six source adapters + tests/adapters | ✅ |
| Shared core + unit/security | ✅ |
| 36-cell packaging | ✅ |
| Installer dry-run/install/verify/drift/uninstall | ✅ integration + transaction |
| Source CLI isolation + immutability | ✅ `tests/security/*` |
| Public-tree hygiene | ✅ |
| Live UI 36 / dual-OS full release | 正確標 not-run / no（措辭見 I1） |
| Multi-seat review partial | 合理；raw logs 不 ship |

### 6. Provenance / NOTICE / clean-room honesty

| 檢查 | 結果 |
|---|---|
| 未宣稱 “never inspected” 裝機 bundle | NOTICE + `test_provenance_honesty` 禁止該用語 |
| compatibility / independently authored reimplementation | NOTICE、provenance、attestation 一致 |
| 禁止 `~/.grok/bundled/skills/**` | README / provenance / CONTRIBUTING / SECURITY 一致；src 無 load bundle |
| Attestation scoped（不蓋 live UI / dual-OS） | clean-room-attestation + provenance 明確 |
| Schema `x-portable-resume-max-total-utf8-bytes` 8 MiB | schema + bounds + provenance 敘述一致 |

### 7. SECURITY.md / CONTRIBUTING.md

- Threat model（untrusted stores、inert handoff、installer collision、zstd process boundary）對得上 snapshot / sanitize / transaction / codex zstd。
- Residual risks（best-effort redaction、global install 危險）與 README Limitations 一致。
- Contributing fixture rules 與 `fixture_manifest.py` 嚴格鍵集合一致。
- 未發現與 code 衝突的安全操作指南。

### 8. evidence-summary.md

- unittest / self-check / matrix 36 / live 0 / self_verify 路徑與 scripts **一致**。
- Multi-seat 只摘要、raw logs 不 ship：**誠實**。
- Not claimed 清單與 STATUS / README **一致**。

### 9. opensource-readiness-final.md

- 「153 tests」：`def test_` 計數 = **153** ✅  
- hygiene / provenance / SECURITY+CONTRIBUTING / self_verify：**與 tree 一致**  
- Remote public URL 本稽核未驗證網路狀態（非 code 對照範圍）

### 10. Dead `.omc/research` in **user-facing** top docs

- README / STATUS / evidence-summary：**無** `.omc/research/` 必要連結 ✅  
- CONTRIBUTING 僅政策「不要 commit」✅  
- `docs/superpowers/plans/...` 歷史 plan 仍引用 `.omc/research`（計畫文件，可接受；非 quick-start 路徑）

---

## Minor nits

1. **README Docs 表**未列 `docs/clean-room-attestation.md`、`docs/opensource-readiness-final.md`（可選）。
2. **Activation 細節**：host-support 表格比 `catalog.activation_help` 略短（claude auto-select by description 未寫）。
3. **CI 用 `python`、docs 用 `python3`**：GH Actions setup-python 下無差。
4. **`SOURCE_KEYS` 雙份定義**：`model.py` 與 `diagnostics.py` 各一份（文件未提及；維護風險非 docs 錯誤）。
5. **`matrix_report` 永遠 `live_cells_supported: 0`**：與 docs「live not-run」一致；若未來有 live smoke，docs 與 code 需同步，否則會變假宣稱。
6. **zstd 路徑**：SECURITY 說 trusted decoder path only——code 僅 `/usr/bin`、`/usr/local/bin`、`/opt/homebrew/bin` 的 `zstd`；docs 未列路徑細節（可接受）。

---

## Checklist：建議精確 file:line 修復

| # | 嚴重度 | 檔案:行 | 建議修改 |
|---|---|---|---|
| 1 | CRITICAL | `docs/host-support.md:33` | 刪除 `.omx/context/host-profile-official-evidence-20260720.md` 連結；改「local planning notes (not shipped)」或把必要 URL 內嵌進本檔 |
| 2 | CRITICAL | `docs/source-formats.md:22` | 刪「tracked public evidence under `.omx/context/`」；改 synthetic fixtures + 已 ship 的 docs 為唯一 public 依據 |
| 3 | HIGH | `tests/unit/test_provenance_honesty.py:27-30` | 擴充 assert：user-facing docs 不得含必要 `.omx/` 路徑（至少 host-support / source-formats / README / STATUS / evidence-summary） |
| 4 | HIGH | `docs/STATUS.md:21` | Linux 列勿寫單純 `not-run`；改為「Ubuntu CI 有跑 deterministic gate，但 dual-OS **release claim** 未建立」 |
| 5 | MEDIUM | `docs/source-formats.md` 全文 | 為各 format 加可連結 heading（對齊 fixture `provenance_ref`），或統一 fixture 錨點到既有 section |
| 6 | MEDIUM | `docs/source-formats.md:7-14` | 補 `opencode-export-file-v1`；將 `G002 status` 更名或定義 |
| 7 | MEDIUM | `README.md:28` / `CONTRIBUTING.md:7` / CI | 註明 CI 僅 3.12；或 matrix 加 3.11 |
| 8 | LOW | `README.md:35-55` | 可註「`PYTHONPATH=src` 可選（scripts 已 inject）」 |
| 9 | LOW | `README.md:91-101` Docs 表 | 可選加入 clean-room-attestation |
| 10 | LOW | `docs/host-support.md:18` | 可選補 claude「model may auto-select by description」（對齊 catalog） |
| 11 | LOW | `docs/superpowers/plans/2026-07-20-open-source-readiness.md:347` | 若保留 plan：將 Step 4 改回未完成或加 note「host-support/source-formats 仍有 .omx 殘留（見本 audit）」——避免 plan 勾選誤導 |

**不在本稽核修改範圍：** 產品 code、測試行為、installer 邏輯（僅建議測試補洞 #3）。

---

## 總結表（稽核問題對照）

| # | 必須檢查項 | 結果 |
|---|---|---|
| 1 | README claims（六來源、命令、install、self_verify、CI、limitations） | **大多準確**；PYTHONPATH 可選；limitations 誠實 |
| 2 | STATUS done/not-done vs src/tests | **大多準確**；Linux not-run 措辭過強（I1） |
| 3 | host-support vs HOST_PROFILES | **roots/activation 準確**；`.omx` 死鏈 critical |
| 4 | source-formats Format IDs vs adapters | **主 ID 全準**；export ID 缺列；假 `.omx tracked`；錨點空洞 |
| 5 | provenance / NOTICE / attestation | **誠實、scoped** |
| 6 | SECURITY / CONTRIBUTING | **準確** |
| 7 | evidence-summary vs reality | **準確** |
| 8 | Dead `.omc`/`.omx` public links | **`.omc/research` 主 docs 已清**；**`.omx` 仍殘** |
| 9 | Python version claims | **3.11+ recommended 合理但未 CI 證明** |
| 10 | matrix packaging 36 / live 0 | **與 code/tests 完全一致** |

---

## Recommendation for docs maintainers

1. **先修 C1**（兩處 `.omx`）——這是 public clone 可直接踩到的錯。  
2. 補 provenance honesty 測試，防止回歸。  
3. 澄清 Linux/CI vs dual-OS release 用語。  
4. 其餘 MEDIUM/LOW 可隨下一輪 docs PR。

**本報告結論維持：MOSTLY ACCURATE WITH FIXES**（非 MISLEADING 產品行為，但 public evidence 路徑必須修）。
