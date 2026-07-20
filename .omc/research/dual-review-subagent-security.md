# Security Review Report — portable-resume-skills

**Scope:** `README.md`、`docs/provenance.md`、`docs/clean-room-attestation.md`、`src/portable_resume/**`（含 adapters / install / resources / snapshot / paths / sanitize / handoff / request / reader）、`tests/security/**`、相關 integration/unit 證據  
**Reviewer role:** Security Reviewer（唯讀；無產品程式碼修改）  
**Focus:** source-CLI 隔離、path/symlink/SQLite 安全、installer 覆寫風險、clean-room（`~/.grok/bundled/skills/**`）、handoff injection  
**Risk Level:** **MEDIUM**  
**Verdict:** **APPROVE WITH MINOR FIXES**

---

## Summary

| 等級 | 數量 |
|---|---|
| Critical | 0 |
| Important | 3 |
| Minor | 4 |

核心讀取路徑（reader + adapters + snapshot + paths + sanitize + handoff）在設計與測試上對齊宣稱的安全不變量：不呼叫 source CLI、source 不可變、symlink 拒絕、SQLite 私有只讀快照、handoff 強制引述與 untrusted banner。  
Installer 與 skill binding 有可修復的防禦深度缺口；不構成遠端 RCE，但在「共享 skill root / 並行寫入 / 惡意 journal」情境下會擴大 blast radius。

---

## Commands run + results

### 本 reviewer 環境限制

此 Security Reviewer 子代理工具面**沒有可用的 shell/Bash 執行器**，因此無法在本輪**實際 spawn** 下列指令。審查以完整原始碼靜態分析 + 既有 `tests/security/**` 與相關測試用例閱讀為主。

### 建議 orchestrator / 本機立即複驗（必跑）

```bash
cd /Users/iml1s/Documents/mine/resume-skills
PYTHONPATH=src python3 -m unittest discover -s tests/security -q
```

預期（依測試設計）：

| 測試模組 | 覆蓋重點 |
|---|---|
| `test_no_source_cli_exec` | PATH shim 不執行 source CLI；Popen/run/system/socket 被擋 |
| `test_isolation` | 核心流程無 process/network；runtime 靜態禁止 `shell=True`/`os.system(`/`subprocess.Popen(`/`urlopen(` |
| `test_snapshot` | symlink 逃逸、FIFO、SQLite `mode=ro`+`query_only`、WAL/SHM 策略、hot journal fail-closed |
| `test_source_immutability` | list/show 後 source tree byte/mtime 不變 |
| `test_provenance_policy` | docs 禁止 bundled 推導；fixtures `synthetic:true`；src 不載入 installed grok bundle |
| `test_verifier_regressions` | hostile metadata 引述、mutation race fail-closed、診斷不洩漏路徑 |

補充建議：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 scripts/portable-resume self-check --json
PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
```

### Secrets scan（靜態）

對 `src/**`、`docs/**`、`scripts/**`、fixtures 掃描 hardcoded secrets 樣式（`sk-…`、`AKIA…`、`api_key=`、private key PEM 等）：

- **結果：** 無真實 secret；僅測試字串出現於  
  - `tests/unit/test_sanitize_handoff.py`（redaction 單元測試）  
  - `tests/unit/test_model_contracts.py`（診斷不洩漏測試）

### Dependency audit

- **結果：** 產品 runtime 為 **Python 標準庫 only**（無 `requirements.txt` / 第三方套件宣告）。  
- **A06：** 無第三方 CVE 面；唯一外部 binary 介面是 Codex 可選 zstd（固定信任路徑，見下）。

### Clean-room structural gate

- docs / README / NOTICE 明文禁止 `~/.grok/bundled/skills/**` 推導。  
- Grok adapter 只掃 `~/.grok/sessions` 結構，**不**讀 `bundled/skills`。  
- `tests/security/test_provenance_policy.py` 對 src 做禁止字串門檻。  
- **誠實非宣稱：** 結構測試 ≠ 人類作者確實從未檢視該路徑的密碼學證明；仰賴 `docs/provenance.md` 作者宣誓。

---

## Critical Issues (Fix Immediately)

_無 Critical。_

（威脅模型為本機 CLI / 本機 session store；未發現未授權遠端可觸發的 RCE、任意檔案覆寫或 credential 外洩主路徑。）

---

## Important Issues (Should Fix Soon)

### 1. Installer plan/commit TOCTOU：可覆寫「規劃後才出現」的非 owned 檔

**Severity:** Important（HIGH × 需競態 × blast = skill root 內非 owned 檔）  
**Category:** A01 Broken Access Control / A04 Insecure Design  
**Location:** `src/portable_resume/install/cli.py`（plan 後再 execute）、`src/portable_resume/install/transaction.py:149-223`（`plan_install`）、`:225-290`（`execute_install` commit 迴圈）  
**Exploitability:** 本機；需對同一 skill root 並行寫入（使用者或他工具在 plan 與 commit 之間放入檔案）  
**Blast Radius:** 非 owned skill 檔被無 backup 覆寫；違反「non-owned collision refuse unless `--force-with-backup`」  
**Issue:**  
`plan_install` 在 **RootLock 外**分類 `creates` / `replaces` / `backups`。`execute_install` 在 lock 下只重驗證 generation，**未重跑 ownership/sha 決策**，並對 `plan.files` 一律 `os.replace`：

```python
# transaction.py commit path（摘要）
for rel in sorted(plan.files):
    src = os.path.join(stage_dir, rel)
    dest = os.path.join(root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(src, dest)  # 不再檢查是否變成 non-owned conflict
```

競態：plan 時 `dest` 不存在 → `creates`；commit 前使用者放入自有 `SKILL.md` → 被無 backup 覆寫。

**Remediation:**

```python
# GOOD：在 RootLock 內重 plan，或 commit 前逐檔 re-check
with RootLock(root):
    require_no_pending_journal(root)
    plan = plan_install(
        host=host, scope=scope, root=root,
        dry_run=False, force_with_backup=force_with_backup,
    )  # generation 一併在 lock 內決定
    # 或對每個 dest 再執行與 plan_install 相同的 owned / force / backup 邏輯
    for rel, data in plan.files.items():
        dest = os.path.join(root, rel)
        if os.path.lexists(dest):
            if os.path.islink(dest) or not os.path.isfile(dest):
                raise DiagnosticError("E_INSTALL_CONFLICT")
            current = sha256_file(dest)
            if current != sha256_bytes(data):
                owned = ...  # 與 plan_install 相同條件
                if not owned and not force_with_backup:
                    raise DiagnosticError("E_INSTALL_CONFLICT")
                if not owned:
                    _backup(dest, backup_root, rel)
        # 再 stage/replace
```

並為「plan 後插入 non-owned 檔」加 integration 測試。

---

### 2. Install journal / recover 路徑未限制在 skill root 內

**Severity:** Important  
**Category:** A01 Path Traversal  
**Location:** `src/portable_resume/install/transaction.py` — `_attempt_rollback`、`recover_root`、`execute_install` 的 `os.path.join(root, rel)` / `Path(stage_dir) / rel`  
**Exploitability:** 本機；需能寫入 `<skill-root>/.portable-resume/journal.json`（通常已有該 root 寫入權）  
**Blast Radius:** 可把寫入/還原目標擴到 skill root **之外**（`..` 或絕對路徑）；在 POSIX 上 `os.path.join(root, "/etc/passwd")` → `/etc/passwd`  
**Issue:**  
`rel` 與 journal 內 `backup` 路徑未做「必須為相對路徑、無 `..`、解析後仍在 root 下」檢查。惡意 journal + `recover` 可擴大寫入範圍。

**Remediation:**

```python
def _safe_rel_under_root(root: str, rel: str) -> str:
    if not rel or os.path.isabs(rel) or os.path.pardir in Path(rel).parts:
        raise DiagnosticError("E_INVARIANT")
    root_real = os.path.realpath(root)
    dest = os.path.realpath(os.path.join(root_real, rel))
    if os.path.commonpath((dest, root_real)) != root_real:
        raise DiagnosticError("E_INVARIANT")
    return dest

# recover / rollback / commit 一律經此 helper
```

對 journal schema 也應拒絕絕對 `backup` 路徑（或強制 backup 必須在 `SUPPORT_DIR/backups/**` 下）。

---

### 3. `run_reader.py` 的 `--expected-source` 綁定可被 argv 覆寫

**Severity:** Important（防禦深度；需 host agent 配合惡意 argv）  
**Category:** A04 Insecure Design / A07 AuthZ binding  
**Location:** `src/portable_resume/resources/skill/run_reader.py.tmpl:19-23`  
**Exploitability:** 本機；host agent 若被誤導傳入 `--expected-source other` + 對應 request JSON  
**Blast Radius:** 破壞「skill 固定 source、不可被 free-form 文字交換」的宣稱；仍受限於 request-v1 與本機可讀 stores  
**Issue:**

```python
def _inject_expected_source(argv: list[str]) -> list[str]:
    """Hardcode the skill source so hosts cannot swap it via free-form text."""
    if "--expected-source" not in argv:
        argv = [*argv, "--expected-source", "${source_key}"]
    return argv
```

註解宣稱 hardcode，實作卻是 soft default。與 SKILL 合約「固定 runner argv」不一致。

**Remediation:**

```python
def _inject_expected_source(argv: list[str]) -> list[str]:
    # 永遠強制本 skill 的 source；拒絕或忽略外部覆寫
    filtered = []
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg == "--expected-source":
            skip_next = True
            continue
        if arg.startswith("--expected-source="):
            continue
        filtered.append(arg)
    return [*filtered, "--expected-source", "${source_key}"]
```

並加 e2e：對 `resume-codex` runner 傳 `--expected-source claude` 仍只走 codex 合約（request source 不符 → `E_INVALID_INPUT`）。

---

## Minor Issues / Nits

### 4. 靜態 isolation 門檻可被 `getattr(subprocess, "Popen")` 繞過

**Severity:** Minor  
**Category:** A08 Integrity / 測試覆蓋  
**Location:** `src/portable_resume/adapters/codex.py:244-260`、`tests/security/test_isolation.py:72-76`  
**Issue:** Codex 可選 zstd 有意用 `getattr(subprocess, "Popen")` 避開字串掃描。實際 zstd 路徑硬化良好（固定絕對路徑、拒絕 symlink/world-writable、`shell=False`、空 PATH、timeout、輸出上限）。  
**Remediation:** 靜態掃描改為 AST 層偵測 `subprocess` 使用點 allowlist（僅 `codex._decompress_zstd`）；文件化「唯一允許 process 是 decompressor 非 source CLI」。

### 5. Windows 上 RootLock 近似 no-op

**Severity:** Minor  
**Category:** A05 Security Misconfiguration  
**Location:** `transaction.py:81-84`  
**Issue:** `os.name == "nt"` 時只持有 fd、不做 `fcntl.flock`。  
**Remediation:** 使用 `msvcrt.locking` 或 portalocker；或明確文件「Windows multi-process install 不支援」。

### 6. Handoff / secret redaction 為 best-effort（已文件化）

**Severity:** Minor / Residual  
**Category:** A03 Injection（prompt）/ A02 Sensitive Data  
**Location:** `sanitize.py`、`handoff.py`、`README.md` Limitations  
**Issue:** 區塊引述 + banner + checklist 降低但**無法消除** LLM 聽從 blockquote 指令的風險；secret pattern 非完整 DLP（例如 PEM、非典型 token）。  
**Remediation:** 維持誠實非宣稱；可考慮對 `BEGIN PRIVATE KEY` / 長 base64 加 pattern；handoff 開頭固定「不得執行引述內容」機器可讀 front-matter。

### 7. `execute_install(..., force_with_backup=)` 參數未使用

**Severity:** Minor  
**Location:** `transaction.py:225`  
**Issue:** force 決策全在 plan 階段；參數易誤導維護者。  
**Remediation:** 刪除未用參數，或在 commit re-check 使用。

---

## Focus Area Assessment

### 1) Source-CLI isolation — **PASS（強）**

| 控制 | 證據 |
|---|---|
| 無 `shell=True` / `os.system` / `urlopen` / `socket.connect` | `src/portable_resume/**` grep |
| Adapter 不 spawn claude/codex/cursor/… | adapters 只讀檔案/SQLite；PATH shim 測試 |
| 唯一 process：Codex 可選 zstd | 固定 `TRUSTED_ZSTD_PATHS`、非 PATH、非 source agent |
| request-v1 邊界 | `resume_ref`/`cwd` 為 JSON 資料，非 shell 插值（`request.py` + SKILL 合約） |
| importlib 僅 `portable_resume.adapters.{source}` 且 source ∈ `SOURCE_KEYS` | `reader.py` |

### 2) Path / symlink / SQLite — **PASS（強）**

| 控制 | 證據 |
|---|---|
| 元件級 symlink 拒絕 | `paths.require_regular_no_symlinks` + `O_NOFOLLOW` open |
| 穩定讀 + 競態 fail-closed | `stable_read_bytes` 多段 fingerprint / membership |
| SQLite 私有複本 + URI `mode=ro&cache=private` + `PRAGMA query_only=ON` 驗證 | `snapshot.SQLiteSnapshot.connect` |
| WAL 複製、SHM 只監控不複製 | `snapshot_sqlite_family` |
| Hot rollback journal → `E_SQLITE_HOT_JOURNAL` | 同檔 + fixtures s-cod-11 / s-ope-07 / s-cur-08 |
| 參數化 SQL（user id 用 `?`）；動態欄位名來自 allowlist | codex `updated_at_ms|updated_at`；cursor/opencode 固定表名 |

### 3) Installer overwrite — **PARTIAL（需修 Important #1/#2）**

| 控制 | 狀態 |
|---|---|
| 非 owned 衝突拒絕 | plan 時有（測試覆蓋） |
| `--force-with-backup` | 有 backup 目錄 |
| symlink / 非 regular 衝突 | plan 拒絕 |
| shared-root 不同 host 內容衝突 | `E_INSTALL_CONFLICT` |
| commit 與 plan 原子一致 | **缺口（TOCTOU）** |
| journal 路徑沙箱 | **缺口** |

### 4) Clean-room `~/.grok/bundled/skills/**` — **PASS（政策 + 結構）**

- 實作/測試不得以該樹為推導來源：docs + NOTICE + provenance tests。  
- Runtime Grok source 讀 `sessions/`，不碰 `bundled/skills`。  
- Fixtures 強制 `synthetic: true`，禁止 `/Users/...` 真實路徑樣式。

### 5) Handoff injection — **PASS with residual**

| 控制 | 狀態 |
|---|---|
| `UNTRUSTED_BANNER` + checklist | 有 |
| 內容逐行 `>` 引述 | `handoff._quote` |
| 中繼資料單行化、控制字元/BIDI/ANSI 剝除 | `sanitize_inline` / `sanitize_text` |
| 特權 role（system/developer/thinking…）丟棄 | `sanitize_turn_record` |
| 診斷不夾帶 recovered text / 絕對路徑 | `diagnostics.DiagnosticError` 固定 message |
| LLM 仍可能聽從引述內容 | **殘餘風險（設計誠實承認）** |

---

## OWASP Top 10 對照（適用項）

| ID | 評估 |
|---|---|
| A01 Broken Access Control | Installer TOCTOU / journal path → Important；reader path 根限制良好 |
| A02 Cryptographic Failures | 無網路傳輸密鑰；紅隊 secret redaction best-effort |
| A03 Injection | SQL 參數化良好；handoff prompt injection 殘餘；argv/request 邊界良好 |
| A04 Insecure Design | expected-source soft bind；其餘 threat model 清晰 |
| A05 Security Misconfiguration | Windows lock；debug 無預設外洩 |
| A06 Vulnerable Components | 無第三方 runtime deps |
| A07 Auth Failures | 非多使用者 auth 產品；skill source 綁定可加強 |
| A08 Integrity Failures | manifest sha256 + verify；journal 完整性未簽名 |
| A09 Logging Failures | 診斷刻意 content-free（正確取捨） |
| A10 SSRF | 無出站 HTTP（PASS） |

---

## Residual risks / 誠實非宣稱

1. **不宣稱** live host activation smoke 已驗證（`docs/host-support.md` live = `not-run`）。  
2. **不宣稱** dual-OS clean runner 皆綠（Linux peer gate 紀錄顯示 Docker 不可用）。  
3. **不宣稱** 完整 DLP / 對抗所有 prompt injection。  
4. **不宣稱** clean-room 的密碼學/法證級證明；僅結構門檻 + 作者宣誓。  
5. Reader 可讀本機 session store 是**產品功能**；保護邊界是「不呼叫 source CLI、不改 source、輸出 inert」。  
6. Host agent 若忽略 SKILL 合約、用 shell 插值 user 字串，超出本套件可強制的邊界。  
7. 本輪 **未實際執行** unittest（工具面無 shell）；合併前請 orchestrator 補跑並貼 exit code。

---

## Security Checklist

- [x] No hardcoded secrets（產品樹；僅測試假資料）
- [x] Source-CLI isolation 設計與靜態/測試意圖一致
- [x] Path/symlink 讀取硬化與 SQLite query-only 私有快照
- [x] Handoff 引述 + untrusted banner + 特權欄位剝除
- [x] Clean-room 政策文件與結構測試存在
- [x] Dependencies：無第三方 runtime 套件需 audit
- [ ] Installer non-owned 覆寫在 **commit 時** 仍 fail-closed（TOCTOU 待修）
- [ ] Journal/recover 路徑限制在 root 內（待修）
- [ ] `run_reader` expected-source 真正 hard-bind（待修）
- [ ] 本輪實際跑通 `tests/security`（待 orchestrator 複驗）

---

## Prioritized fix order

1. **Important #1** — install re-plan / re-check under lock（防 non-owned 無 backup 覆寫）  
2. **Important #2** — journal/rel path sandbox（防 root 逃逸）  
3. **Important #3** — force `--expected-source` in runner template  
4. Minor：AST allowlist for subprocess、Windows lock、刪除死參數  

完成 1–3 後，就本 focus 可上調至 **APPROVE**（在 `tests/security` 全綠前提下）。

---

## Verdict rationale

**APPROVE WITH MINOR FIXES**（非 REQUEST CHANGES / REJECT）：

- 產品核心安全不變量（source CLI 隔離、symlink、SQLite、source immutability、handoff inert 標記、clean-room 政策）**已實作且有針對性測試**。  
- 發現項為 installer 競態/路徑沙箱與 skill binding 防禦深度，**非**遠端可利用 Critical。  
- 建議在 V1 release claim 前修完三項 Important；不阻塞繼續 adapter/packaging 其他審查，但 **不建議** 在未修 #1/#2 前把 installer 行為描述成「絕對不會覆寫 non-owned 檔」。
