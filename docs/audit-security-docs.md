# Security Documentation Audit Report

**日期：** 2026-07-20  
**範圍：** 文件宣稱 vs 實際安全控制（唯讀稽核）  
**Verdict：** **NEEDS FIXES**

| 項目 | 結論 |
|---|---|
| 威脅模型是否足以公開 OSS？ | **大致可用，但對公開消費仍偏簡**（缺供應鏈／暫存機敏／平台差異／明確 out-of-scope） |
| 是否有虛假安全承諾？ | **無嚴重誤導**；少數 README 安全條目過度簡化 |
| 是否缺重要警告？ | **有**（見 Medium/High 文件缺口） |
| Installer `global` / `force` 是否有文件？ | **SECURITY.md 有；README 不足** |
| Secret redaction 是否誠實？ | **高層誠實（best-effort）**；缺覆蓋範圍說明，易產生過度信任 |

**Risk Level（文件誠實度 / 公開 OSS 就緒）：** **MEDIUM**

## Summary

| 嚴重度 | 數量 | 說明 |
|---|---:|---|
| Critical | 0 | 無「文件宣稱安全但實作完全相反」的 CRITICAL 文件謊言 |
| High | 2 | 供應鏈／skill 安裝風險說明不足；密鑰脫敏覆蓋範圍未揭露 |
| Medium | 5 | README 安全條目簡化、global/force 文件不均、zstd 程序例外、回報管道弱、暫存／平台殘餘風險 |
| Low | 3 | 歷史掃描未提、Windows flock、測試靜態守衛與 `getattr(Popen)` 取巧 |

**對照後的控制實作品質（非本報告主要交付，但影響 verdict）：** 實際程式控制明顯強於文件深度——路徑圍籬、來源不可變、SQLite 私有副本、`query_only`、handoff 引用、zstd 白名單解碼等均有測試佐證。問題在**公開文件完整度與警告層級**，而非「文件說有控制但 code 完全沒做」。

---

## 稽核方法

1. 閱讀：`SECURITY.md`、`README.md`（Safety / Limitations）、`docs/provenance.md`、`docs/clean-room-attestation.md`、`CONTRIBUTING.md`、`docs/STATUS.md`
2. 對照實作：
   - `src/portable_resume/install/transaction.py`（path containment、force backup、journal/rollback）
   - `src/portable_resume/adapters/codex.py`（zstd process boundary）
   - `src/portable_resume/sanitize.py`、`handoff.py`、`snapshot.py`
   - `src/portable_resume/install/cli.py`、`catalog.py`
3. 安全測試：`tests/security/*`、`tests/unit/test_sanitize_handoff.py`、`tests/integration/test_*installer*`、Codex zstd fixtures/tests
4. Secrets / deps：
   - 產品樹門檻：`scripts/check_secrets.py` + `tests/security/test_public_tree_hygiene.py`
   - **無第三方 runtime 依賴**（stdlib only）→ `npm audit` / `pip-audit` 不適用

---

## 文件 vs 控制對照表

### A. 威脅模型（`SECURITY.md`）

| 宣稱 | 實作證據 | 判定 |
|---|---|---|
| 本地、離線友好；非網路服務 | reader 路徑無 `urlopen`/`socket.connect`；`tests/security/test_isolation.py` 擋 network API | **符合** |
| 不還原 live process | 設計與 handoff 文案一致；STATUS 誠實標 `live_supported: False` | **符合** |
| 來源 store 不可變 | `snapshot.stable_read_bytes` / SQLite 私有副本；`test_source_immutability` / `test_snapshot` | **符合** |
| 路徑逃逸／symlink／特殊檔 | no-follow regular files、`E_UNSAFE_PATH`、FIFO/dir 拒讀 | **符合** |
| 安裝覆寫防護 | non-owned → `E_INSTALL_CONFLICT`；`--force-with-backup` 才備份覆寫 | **符合** |
| zstd：固定 argv、無 shell、caps/timeouts | `TRUSTED_ZSTD_PATHS`、`shell=False`、`PATH=""`、5s timeout、輸出上限 | **符合** |
| Secret redaction best-effort | `sanitize.py` 有限 regex；README/SECURITY 均寫 best-effort | **高層符合；細節不足** |
| `install --scope global` / `--force-with-backup` 強大 | CLI 真有 flags；測試覆蓋 force backup | **SECURITY 有；README 偏弱** |

### B. README Safety invariants

| 宣稱 | 判定 | 備註 |
|---|---|---|
| Recovered content is inert/untrusted and sanitized | **半真** | inert **依賴目的端 agent 遵守 banner/checklist**；sanitized ≠ 完整脫敏 |
| Source stores must not change | **真**（設計目標＋測試） | 並發突變 fail-closed，非保證永遠讀得到 |
| Source CLIs never invoked | **真** | PATH shim 測試通過 |
| Installer refuses non-owned collisions unless `--force-with-backup` | **真** | 有 integration test |
| Shared destination roots require byte-identical renders | **真** | codex/antigravity 衝突有文件與測試 |

### C. Path containment / force backup（`transaction.py`）

| 控制 | 位置 | 文件是否充分 |
|---|---|---|
| `_safe_rel_path` 拒絕對路徑 / `..` / NUL | L225–233 | SECURITY 表「path escape」一句帶過，**無 API/行為細節** |
| `_dest_under_root` realpath + `commonpath` | L236–245 | 同上 |
| force：non-owned → backup under `.portable-resume/backups/<id>/` | L203–207, L327–335 | SECURITY 警告「了解哪些路徑會被替換」；**未說明備份落點與殘留第三方 skill 內容** |
| journal 路徑逃逸在 recover 時忽略 | `test_journal_path_escape_is_ignored_on_recover` | **未在 SECURITY 描述** |
| RootLock：POSIX `fcntl`；Windows 僅開檔不 flock | L80–84 | **未文件化平台差異** |

### D. Codex zstd process

| 控制 | 位置 | 文件是否充分 |
|---|---|---|
| 僅信任固定絕對路徑；拒 symlink / world-writable | L51–54, L226–241 | SECURITY trust boundary 有；**README Safety 未提程序例外** |
| `getattr(subprocess, "Popen")` 固定 argv | L252–260 | 為繞過「禁止直接寫 `subprocess.Popen(`」靜態檢查；**SECURITY 誠實，靜態測試語意需讀者小心** |
| 不吃 PATH 上的惡意 `zstd` | `test_s_cod_07_08` | 與「Trusted decoder path only」一致 |

### E. Secret redaction honesty

| 文件說法 | 實作 | 判定 |
|---|---|---|
| best-effort, not complete DLP（README Limitations + SECURITY residual） | 僅 AKIA、gh\*、sk-、Bearer、label=value 等少數 pattern | **誠實方向正確** |
| （無）列出涵蓋／不涵蓋 | 無 JWT、PEM、Slack、Azure、通用 base64、多行密鑰等 | **缺警告 → 易被當完整 DLP** |
| `check_secrets.py` 掃 tracked tree | 不掃 git history、跳過 binary fixtures | **產品門檻合理；限制未寫進 SECURITY** |

### F. Provenance / clean-room

| 文件 | 實作/測試 | 判定 |
|---|---|---|
| 禁止 `~/.grok/bundled/skills/**`、真實 transcript、憑證 | `test_provenance_policy`、fixture `synthetic:true` | **一致** |
| 不呼叫來源 agent CLI 作 recovery backend | isolation / no_source_cli_exec | **一致** |
| 不宣稱 live UI / dual-OS | STATUS、host-support、matrix `live_supported: false` | **一致、誠實** |

---

## High Issues（應盡快補文件）

### 1. 安裝即供應鏈：skill 會被 host agent 執行

**Severity:** HIGH（文件缺口）  
**Category:** A04 Insecure Design / A08 Integrity — 威脅模型殘缺  
**Location:** `SECURITY.md`（全文）；`README.md` Quick start / Safety  
**Exploitability:** 遠端間接——使用者 clone 不可信 fork 後 `install --scope global`（甚至 project）  
**Blast Radius:** 目的端 agent 依 skill 指示寫 request / 跑 `run_reader.py`；惡意 fork 可改 skill body 誘導 host 執行任意 shell（**控制面在 host，不在 reader argv**）  
**Issue：**  
SECURITY residual 只寫「不要在未審查的 fork 上跑 global + force」。對公開 OSS 更關鍵的是：

- **任何 scope 的 install 都會把可執行 skill／runner 寫入 agent skill root**
- Host 可能自動或半自動載入 skill
- 這是主要供應鏈攻擊面，卻沒有獨立「Supply chain / untrusted revision」小節

**Remediation（文件範例）：**

```markdown
## Supply chain

Installing skills writes executable guidance and a Python runner into host skill roots.
Treat every revision you install as code you run with the host agent’s privileges.

- Prefer `--scope project` and `--dry-run` first.
- Review `git` revision / signed tags before `--scope global`.
- `--force-with-backup` can replace non-owned skills; backups land under
  `<root>/.portable-resume/backups/<timestamp>/` and may retain third-party content.
- The reader argv never interpolates user fields; hosts that ignore skill instructions
  and shell-interpolate free text remain out of scope for this tool’s guarantees.
```

### 2. 密鑰脫敏「best-effort」未揭露覆蓋範圍

**Severity:** HIGH（誠實度／過度信任風險）  
**Category:** A02 Cryptographic Failures / Sensitive Data Exposure  
**Location:** `SECURITY.md:30`；`README.md:115`；`src/portable_resume/sanitize.py:15-21`  
**Exploitability:** 本地——session 內非常見格式密鑰會原樣進入 handoff／stdout  
**Blast Radius:** 憑證洩漏到新 session、日誌、剪貼簿、CI 輸出  
**Issue：**  
文件正確說「不是完整 DLP」，但**未列舉實際 pattern**，也未強調 handoff **預設仍可能含密鑰**。實作只覆蓋少數「明顯」形狀。

**Remediation（文件範例）：**

```markdown
### Secret redaction (what it does / does not)

Attempted patterns (non-exhaustive, best-effort):
- AWS access key id `AKIA…`
- GitHub tokens `gh[pousr]_…`, `github_pat_…`
- OpenAI-like `sk-…`
- `Bearer …` and `password|api_key|token|secret = value` label forms

Not a DLP product. Will miss JWTs, PEM blocks, cloud keys with other prefixes,
multiline secrets, obfuscation, and many vendor formats.

Operators must: avoid sharing handoff of private sessions; rotate any credential
that may have appeared in recovered text; never paste handoff into untrusted channels.
```

---

## Medium Issues

### 3. README Safety invariants 過度簡化（相對 Limitations / SECURITY）

**Severity:** MEDIUM  
**Category:** A05 Security Misconfiguration（文件）  
**Location:** `README.md:72-78` vs `README.md:111-115` / `SECURITY.md:28-33`  
**Issue：**  
「inert … and sanitized」放在 Safety 標題下，多數讀者停在此；殘餘風險藏在文末 Limitations。  
**Remediation：** Safety 清單每條加「見 SECURITY residual」或改為：

```markdown
- Recovered content is *marked* inert/untrusted and *partially* sanitized
  (secret redaction is best-effort; see SECURITY.md)
```

### 4. Installer `global` / `force` 文件不均

**Severity:** MEDIUM  
**Category:** A01 Broken Access Control（操作風險）  
**Location:** `SECURITY.md:32,51-52`；`src/portable_resume/install/cli.py:30-37`；README 幾乎只有 force 一句  
**Issue：**  
- `global` 會寫入 `~/.claude/skills`、`~/.agents/skills`、`~/.cursor/skills` 等（`catalog.py`）
- force 會覆寫 non-owned 並保留 backup
- Quick start **只展示 project**，未並列危險 flags 的「不要」範例  

**Remediation：** README Safety 或 Quick start 加：

```bash
# Prefer project scope. Global writes into the user skill roots under --home.
# Avoid unless you reviewed the revision:
#   install --host claude --scope global --force-with-backup
```

並在 SECURITY 補 global root 表（指向 `docs/host-support.md`）。

### 5. Optional zstd 程序邊界未進 README Safety

**Severity:** MEDIUM  
**Category:** A03 Injection / process boundary  
**Location:** `SECURITY.md:26`；`README.md:30`（僅「optional zstd binary」）；`codex.py:244-314`  
**Issue：**  
README 讓人以為 runtime **零子程序**；實際上 Codex `.zst` 會 spawn 白名單 `zstd`。SECURITY 已誠實，README 不一致。  
**Remediation：** Requirements 或 Safety 加：

```markdown
- Optional host `zstd` may be executed only from audited absolute paths
  (`/usr/bin/zstd`, …), fixed argv, no shell, emptied PATH, size/time caps.
  PATH-provided `zstd` is ignored.
```

### 6. 漏洞回報管道偏弱（公開 OSS）

**Severity:** MEDIUM  
**Category:** A09 Logging / Security response  
**Location:** `SECURITY.md:39-47`  
**Issue：**  
「Advisories when enabled」+「owner profile email」無固定 security@、無回應時限、無 PGP。對公開 repo 可接受為起步，但**不足以稱完整 vulnerability management**。  
**Remediation：** 啟用 GitHub Security Advisories；填固定聯絡；可選 90 天 disclosure 政策。

### 7. 殘餘風險清單缺暫存副本與失敗模式

**Severity:** MEDIUM  
**Category:** A02 / A04  
**Location:** `SECURITY.md` Residual risks；`snapshot.py` 私有 SQLite temp  
**Issue：** 未說明：

- SQLite 讀取會把 DB（+wal）**複製到暫存目錄**（含 session 內容）後 query_only
- 崩潰／權限異常時 temp 清理 best-effort
- Handoff 輸出到 stdout 可能被 host 日誌長期保留
- Host 忽略 skill「勿 shell 插值」時的 **out-of-scope**

**Remediation：** Residual risks 增補上列；加 **Out of scope** 小節。

---

## Low Issues

### 8. `check_secrets` 不掃 git history

**Severity:** LOW  
**Location:** `scripts/check_secrets.py`；`SECURITY.md` 未提  
**Issue：** 只掃 `git ls-files`。歷史中曾提交的密鑰不會被擋。  
**Remediation：** SECURITY 或 CONTRIBUTING 註明；發布前建議 `git log -p` / gitleaks 一次。

### 9. Windows RootLock 不 flock

**Severity:** LOW  
**Location:** `transaction.py:80-84`  
**Issue：** `os.name == "nt"` 跳過 `fcntl.flock`，並發 install 互斥弱。  
**Remediation：** SECURITY 標「Windows locking best-effort / not primary target」。

### 10. 靜態隔離測試與 zstd 的 `getattr(Popen)` 

**Severity:** LOW（測試／文件語意）  
**Location:** `tests/security/test_isolation.py:72-76`；`codex.py:252`  
**Issue：** 測試斷言 runtime 文字不含 `subprocess.Popen(`，但 zstd 用 `getattr` 合法繞過。控制本身合理，文件應明確「**唯一**允許的子程序是可信 zstd 解碼」。  
**Remediation：** SECURITY zstd 列加「static source guard intentionally allows only this indirect launch site」。

---

## 威脅模型是否足夠公開 OSS？

| 面向 | 評分 | 說明 |
|---|---|---|
| Assets / trust boundaries 表 | 良好 | 四邊界清楚 |
| Residual risks 誠實度 | 良好起步 | DLP、prompt injection、global/force 有點到 |
| 供應鏈 / 惡意 fork | **不足** | 應升格為一等章節 |
| 資料生命週期（temp、stdout、backup） | **不足** | |
| 平台支援與鎖定語意 | **不足** | |
| 漏洞回應流程 | **勉強** | 需固定聯絡與 Advisories |
| 與實作／測試一致性 | **高** | 少見「文件吹牛、code 沒做」 |

**結論：** 對「實驗性、deterministic V1、macOS」成熟度標籤而言，SECURITY.md **方向正確且整體誠實**；若目標是**陌生使用者可安全評估與安裝的公開 OSS**，仍需補上列 High/Medium 文件，故 **NEEDS FIXES**（非 MISLEADING）。

---

## 虛假安全承諾？

| 候選語句 | 是否虛假？ |
|---|---|
| inert / untrusted | **否**（標記 + 引用 + checklist；依賴 host 遵守——SECURITY 有 residual） |
| sanitized | **略膨** 若解讀為完整淨化；有 Limitations 對沖 |
| never invoke source CLI | **真** |
| source stores must not change | **真**（意圖＋測試；並發則 fail-closed） |
| not a network service | **真** |
| secret redaction best-effort | **真**（誠實） |
| live UI / dual-OS | **未虛假宣稱**（明確 not-run） |
| runtime 無任何 process | README **暗示**；SECURITY 已除外 zstd → **輕度文件不一致，非惡意謊言** |

**總評：非 MISLEADING**；最大風險是**簡化句被截斷引用**，而非系統性欺騙。

---

## 安全檢查清單（本稽核）

- [x] 無 hardcoded 產品密鑰（tracked tree 門檻 + hygiene 測試）
- [x] 主要輸入路徑有邊界／fail-closed（reader / snapshot / installer）
- [x] Injection：SQL 參數化、handoff 引用、無 `shell=True`
- [x] AuthN/Z：N/A（本地 CLI；安裝 ownership/claims 有）
- [x] 依賴：stdlib only，無第三方 CVE 面
- [ ] 文件威脅模型對公開 OSS **完整**（本報告要求修復）
- [ ] Secret redaction 覆蓋範圍已寫清
- [ ] Installer global/force 在 README 與 SECURITY 對稱警告
- [ ] 供應鏈 / temp 機敏 / out-of-scope 已補

---

## 建議修復優先序（僅文件；本稽核不改 code）

1. **P0：** SECURITY 增 Supply chain + Secret redaction coverage + Out of scope  
2. **P0：** README Safety 與 Limitations 對齊（inert/sanitized 用語；global/force；zstd 程序例外）  
3. **P1：** force backup 落點與 global roots 交叉連結 `host-support.md`  
4. **P1：** 啟用 GitHub Security Advisories + 固定回報聯絡  
5. **P2：** Windows lock、secrets history scan、getattr(Popen) 語意註記  

---

## OWASP 速覽（文件／控制對應）

| OWASP | 文件狀態 | 控制狀態 |
|---|---|---|
| A01 Access Control | global/force 警告不均 | 安裝 ownership + conflict 良好 |
| A02 Crypto / Secrets | best-effort 誠實但不完整 | 有限 regex 脫敏；非加密產品 |
| A03 Injection | prompt injection 有 residual | 引用 handoff、參數化 SQL、無 shell |
| A04 Insecure Design | 缺供應鏈章 | 本地離線設計合理 |
| A05 Misconfig | README 簡化 | dry-run、verify、journal 尚可 |
| A06 Vulnerable Components | N/A stdlib | 無第三方 runtime |
| A07 Auth Failures | N/A | N/A |
| A08 Integrity | 弱（fork install） | package identity / verify_root 有 |
| A09 Logging / Response | 回報管道弱 | 診斷碼穩定；無安全事件遙測（合理） |
| A10 SSRF | N/A（無外連） | 無 URL fetch |

---

## Verdict

# **NEEDS FIXES**

**理由（摘要）：**

1. 實作與 SECURITY 核心宣稱**大多一致且偏誠實**，未達 MISLEADING。  
2. 對公開 OSS 仍缺：**供應鏈（install=run skill）**、**脫敏覆蓋清單**、**資料殘留（temp/stdout/backup）**、**README/SECURITY 對稱警告**。  
3. 補齊上列文件後，可評估升為 **ADEQUATE**（在 maturity 仍標 experimental 的前提下）。

---

## 附錄：關鍵程式錨點

| 主題 | 檔案:行（約） |
|---|---|
| Threat model 文件 | `SECURITY.md:1-54` |
| README Safety / Limitations | `README.md:72-78`, `111-115` |
| Path safe + force backup | `install/transaction.py:149-222`, `225-245`, `275-371` |
| zstd trusted spawn | `adapters/codex.py:51-54`, `226-314` |
| Secret patterns | `sanitize.py:15-21`, `104-116` |
| Handoff security banner | `handoff.py:12-16`, `59-92` |
| Install CLI flags | `install/cli.py:30-37` |
| Security tests | `tests/security/*` |
| Force backup test | `tests/integration/test_matrix_and_installer.py:117-140` |
| Secrets gate | `scripts/check_secrets.py` |

---

*本報告為文件誠實度與威脅模型完整性稽核；不修改產品程式碼。*
