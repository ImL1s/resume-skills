# Security Review Report

**日期：** 2026-07-20  
**審查類型：** Senior security review（公開 OSS 就緒 + open-source prep + Codex zstd list degrade 修復後）  
**範圍：** tracked 產品樹、`src/portable_resume/**`、`scripts/**`、`tests/security/**`、`.github/**`、`SECURITY.md` / `README.md`  
**語言／框架：** Python 3 stdlib only（無第三方 runtime 依賴）  
**遠端：** `https://github.com/ImL1s/resume-skills`（PUBLIC）  
**模式：** 唯讀審查（本報告不修改產品程式碼）

**Risk Level：** **LOW**（公開釋出；無殘留 Critical／Important 阻擋項）  
**Assessment: Ready for public?** **Yes**

---

## Summary

| 嚴重度 | 數量 | 說明 |
|---|---:|---|
| Critical | 0 | 無遠端可利用 RCE／密鑰外洩／未圍籬寫入 |
| High / Important | 0 | 安裝路徑圍籬、zstd 程序邊界、list degrade 已就位 |
| Medium（非阻擋） | 1 | uninstall/verify 對 manifest 路徑未重套 `_dest_under_root`（需已能寫 skill root） |
| Low（非阻擋） | 若干 | 歷史 secrets 不在 CI 門檻、Windows flock 較弱、zstd TOCTOU、DLP best-effort |

**結論：** 在「本地、離線、使用者主動執行 CLI／安裝 skill」威脅模型下，**可公開**。殘餘風險屬已知誠實限制或防禦深度，不構成 public-block。

---

## 1. Secrets in tracked tree

### 方法

- 對照 `scripts/check_secrets.py` 與 `tests/security/test_public_tree_hygiene.py` 規則。
- 以 repository 全文掃描：PEM、`ghp_` / `github_pat_`、`AKIA…`、`sk-…`、Slack token、`/Users/…`、`/home/…`、已知私人信箱形狀。
- 合成測試字串僅允許在 `tests/` 以 runtime 拼接（例如 `test_sanitize_handoff.py` 的 `sk-` + 字尾），不寫入產品字面量。

### 結果

| 檢查 | 結果 |
|---|---|
| 產品／文件 hardcoded 密鑰形狀 | **CLEAN** |
| 絕對 home path 外洩 | **CLEAN**（僅出現在 regex／文件模式描述） |
| 私人信箱字面量 | **CLEAN**（hygiene 測試以字串拼接比對禁止形狀） |
| Binary fixtures（`.sqlite` / `.vscdb` / `.zst`） | 刻意跳過文字掃描（與 gate 一致） |
| CI 門檻 | `.github/workflows/ci.yml` 每 job 執行 `python scripts/check_secrets.py` |
| 忽略目錄 | `.omc/research/`、`.omx/` 已在 `.gitignore`；不得進 tracked tree |

**Severity residual：** 無 Critical／Important。  
**殘餘 Low：** gate 不掃 `git log -p` 歷史；`opensource-readiness-final.md` 已記錄作者 email rewrite。建議維持 GitHub secret scanning（見 §4）。

---

## 2. Installer path containment

### 控制現況（安裝／提交／回復路徑）

| 控制 | 位置 | 判定 |
|---|---|---|
| `_safe_rel_path` 拒絕對路徑、`..`、NUL、空 segment | `install/transaction.py:225-233` | **通過** |
| `_dest_under_root`：`realpath` + `commonpath == root_real` | `install/transaction.py:236-245` | **通過**（prefix spoof 類 `startswith` 問題已避開） |
| commit 前每個 rel 再分類（縮短 plan/execute TOCTOU） | `execute_install` | **通過** |
| journal recover 忽略 `../` 與 root 外 backup | `recover_root` + `test_journal_path_escape_is_ignored_on_recover` | **通過** |
| force backup 僅落在 `.portable-resume/backups/` 且還原時再驗 support 前綴 | rollback / recover | **通過** |
| 計劃來源 `materialize_plan` 只產生固定相對路徑 | `install/render.py` | **通過** |

### 殘餘（非 Important）

### R1. uninstall / verify 未重套 destination containment

**Severity：** MEDIUM（非 public-block）  
**Category：** A01 Broken Access Control（本地、需先寫入 skill root）  
**Location：** `src/portable_resume/install/transaction.py:478`（`verify_root`）、`:537`（`uninstall_claim`）  
**Exploitability：** Local；攻擊者已能寫入 skill root 的 `manifest.json`，再誘使使用者執行 `uninstall`  
**Blast Radius：** 可能以 `..` 相對路徑刪除 skill root 外、但使用者程序可寫的檔案（需 hash 吻合 entry）  
**Issue：** 安裝路徑已用 `_dest_under_root`；uninstall/verify 仍 `os.path.join(root, path)`。與「destination containment」完整對稱性不一致。  
**Remediation（建議後續，非阻擋公開）：**

```python
# BAD — uninstall 信任 manifest 字串
abs_path = os.path.join(root, path)
if os.path.isfile(abs_path) and sha256_file(abs_path) == entry.sha256:
    os.remove(abs_path)

# GOOD — 與 install 同一圍籬
try:
    abs_path = _dest_under_root(root, path)
except DiagnosticError:
    retained_drift.append(path)
    del manifest.files[path]
    continue
if os.path.isfile(abs_path) and sha256_file(abs_path) == entry.sha256:
    os.remove(abs_path)
```

**不評為 Important 的理由：** 需既有 skill-root 寫入能力；安裝主路徑與 journal 已圍籬；預設 CLI 不會寫出逃逸 rel。

---

## 3. Codex zstd process safety（degrade fix 後）

### 程序邊界

| 控制 | 位置 | 判定 |
|---|---|---|
| 僅 `TRUSTED_ZSTD_PATHS` 絕對路徑；**忽略 PATH** | `codex.py:51-53, 226-241` | **通過** |
| 拒 symlink、非 regular、world/group writable、`realpath != candidate` | `_trusted_zstd` | **通過** |
| 固定 argv `[-d, -q, -c]`、`shell=False`、`close_fds=True`、`env PATH=""` | `_decompress_zstd` | **通過** |
| 逾時 5s、輸出 ≤ `record_bytes`、失敗 kill | `_decompress_zstd` | **通過** |
| 惡意／損壞 zstd 不拖垮整次 `list()` | `_rollout_summary` 捕捉 `E_CORRUPT_RECORD` / `E_CAPABILITY_UNAVAILABLE` / `E_LIMIT_EXCEEDED` → `None` | **通過** |
| 無 decoder 時略過 `.zst`（sqlite 路徑與 rollout 路徑） | `:418-419`, `:564-565`, probe warnings | **通過** |
| 測試：PATH 上假 zstd 不被呼叫；corrupt list 空結果 | `test_s_cod_07_08_*` | **通過** |
| 顯式 `show` 對 corrupt/unavailable 仍 fail-closed | `CodexAdapter.show` → `_read_rollout` | **預期行為**（正確） |

### 殘餘 Low（非 Important）

- `getattr(subprocess, "Popen")` 為配合靜態「禁止直接 `subprocess.Popen(`」守衛；`SECURITY.md` 已標為**唯一**允許子程序。
- 可信路徑 lstat 與 exec 之間理論 TOCTOU；實務上 `/usr/bin/zstd` 等為系統擁有，風險低。

**Severity residual：** 無 Critical／Important。

---

## 4. GitHub：secret scanning 與 private vulnerability reporting

| 項目 | 狀態 |
|---|---|
| 倉庫公開 | 是（`origin` → `ImL1s/resume-skills`） |
| 文件回報管道 | `SECURITY.md`：優先 GitHub Security Advisories；禁止公開 issue 附真實 transcript／憑證 |
| Secret scanning / private vuln reporting | **本審查依任務假設：parent 已啟用**。無法在唯讀、無 GitHub Admin API 下驗證 UI toggle。 |
| CI secrets gate | 有（`check_secrets.py`） |
| Dependabot | 僅 `github-actions` weekly（合理；無 PyPI 套件） |

**若 parent 實際未啟用：** 屬營運設定缺口，建議立刻在 repo Settings → Code security 啟用 **Secret scanning**、**Push protection**（若可用）、**Private vulnerability reporting**。不構成「程式樹不可公開」判定，但應在合併本報告當下人工確認。

---

## 5. Residual Critical / Important only

### Critical Issues（Fix Immediately）

*無。*

### High / Important Issues（Fix within 1 week）

*無。*

（先前 open-source prep 已處理：research 樹排除、installer `commonpath`、SECURITY 供應鏈／DLP 誠實說明、zstd 可信路徑與 list degrade。）

### 非阻擋殘餘（摘要，非正式 Important 清單）

| ID | 嚴重度 | 項目 |
|---|---|---|
| R1 | MEDIUM | uninstall/verify 路徑圍籬不對稱（§2） |
| R2 | LOW | secrets gate 不掃 git history |
| R3 | LOW | Windows `RootLock` 無 flock |
| R4 | LOW | handoff DLP best-effort（已文件化） |
| R5 | LOW | SQLite 暫存副本／stdout 可能被 host 日誌保留（已文件化） |

---

## OWASP Top 10 對照（適用項）

| 類別 | 評定 | 摘要 |
|---|---|---|
| A01 Broken Access Control | 良好 | 來源 approved roots + no-follow；安裝 ownership/claims；R1 為 uninstall 深度 |
| A02 Cryptographic Failures | N/A／誠實 | 非加解密產品；紅acted best-effort；無 hardcoded 產品密鑰 |
| A03 Injection | 良好 | 無 `shell=True`；SQL 欄位來自固定 signature；handoff 全引用；source CLI 永不呼叫 |
| A04 Insecure Design | 良好 | 本地離線、fail-closed、bounds、inert handoff；供應鏈已寫 SECURITY |
| A05 Security Misconfiguration | 良好 | dry-run、verify、journal recover；無 debug 伺服器 |
| A06 Vulnerable Components | 良好 | **stdlib only**；Actions 由 dependabot 追；無 `pip-audit` 面 |
| A07 Identification/Auth | N/A | 本地 CLI，無網路身份系統 |
| A08 Software/Data Integrity | 中上 | package identity + `verify_root`；第三方 fork 安裝依使用者審查 |
| A09 Logging/Monitoring | 可接受 | 穩定 diagnostic codes；無遙測（合理）；漏洞回報文件已備 |
| A10 SSRF | N/A | 無出站 URL fetch |

---

## Dependency audit

- **Application runtime：** 無 `requirements.txt` / `pyproject` 第三方套件 → **無 CRITICAL/HIGH CVE 應用依賴面**。
- **CI actions：** `actions/checkout@v4`、`actions/setup-python@v5`；`.github/dependabot.yml` 週更 github-actions。
- 未執行 `npm audit` / `pip-audit`（無對應 lockfile）；不適用。

---

## Security Checklist

- [x] No hardcoded secrets（tracked 文字樹 + CI gate + hygiene 測試）
- [x] All inputs validated（request-v1、paths、bounds、fail-closed diagnostics）
- [x] Injection prevention verified（無 shell、參數化／固定 SQL 欄位、quoted handoff）
- [x] Authentication/authorization verified（N/A 網路；安裝 claims／衝突策略有）
- [x] Dependencies audited（stdlib only + Actions dependabot）
- [x] Installer install/commit/recover path containment（`commonpath`）
- [x] Codex zstd trusted-path + list degrade
- [x] Source immutability / no source CLI exec（security tests）
- [ ] uninstall/verify 路徑圍籬與 install 完全對稱（R1，建議後續）
- [ ] 人工確認 GitHub secret scanning + private vuln reporting toggle（§4 假設）

---

## Assessment

# Ready for public? **Yes**

**理由：**

1. Tracked 產品樹無密鑰／私人 home path 外洩跡象；CI 有 secret/path gate。  
2. 安裝寫入主路徑已以 `_safe_rel_path` + `realpath`/`commonpath` 圍籬；journal 逃逸測試覆蓋。  
3. Codex zstd 不走 PATH、固定 argv、有 timeout／輸出上限；**list 對 corrupt/unavailable zstd 僅 degrade 該 session／provider**，不再拖垮整次列舉。  
4. 威脅模型與 SECURITY／README 對「非完整 DLP、非 live UI、唯一子程序為 zstd」說法一致。  
5. 殘留 **Critical = 0、Important/High = 0**；R1 屬本地防禦深度，不阻擋公開。

**公開後建議（非 gate）：**

1. 確認 GitHub **Secret scanning**、**Private vulnerability reporting** 已開（本報告假設 parent 已開）。  
2. 後續 PR 將 `verify_root` / `uninstall_claim` 改走 `_dest_under_root`（R1）。  
3. 維持 `python3 scripts/check_secrets.py` 與 `python3 scripts/self_verify.py` 為 PR 必要綠燈。

---

## 審查範圍檔案（主要）

- `src/portable_resume/adapters/codex.py`
- `src/portable_resume/install/transaction.py`、`cli.py`、`catalog.py`、`render.py`
- `src/portable_resume/paths.py`、`snapshot.py`、`sanitize.py`、`handoff.py`、`request.py`、`bounds.py`
- `scripts/check_secrets.py`、`scripts/self_verify.py`
- `tests/security/*`、`tests/adapters/test_claude_codex_cursor.py`（zstd）、`tests/integration/test_installer_transaction.py`
- `.github/workflows/ci.yml`、`.github/dependabot.yml`
- `SECURITY.md`、`README.md`、`docs/opensource-readiness-final.md`、`.gitignore`
