# Dual Review Report — portable-resume-skills V1（Grok，唯讀）

**審閱者：** Grok 4.5（獨立 dual-review 通道）  
**日期：** 2026-07-20  
**範圍：** 工作樹完整檢視（`main`，依 brief 未做產品程式碼修改）  
**依據 brief：** `.omc/research/dual-review-brief-safe.md`  
**PRD：** `.omx/plans/prd-portable-resume-skills.md`（AC-01..19）  
**既有閘道紀錄：** `.omx/ultragoal/prd-verification.md`、`.omx/ultragoal/independent-review-deferred.md`

---

## Verdict

**APPROVE WITH MINOR FIXES**

判定語意：

- **決定性（deterministic）產品面**可合併／可繼續使用：六來源讀取、inert handoff、路徑／SQLite 穩態讀、36 格 filesystem packaging、installer 基本生命週期、安全測試均有實據，且本機指令全綠。
- **完整 V1 release claim（AC-10 live 36 格 + AC-18 雙 OS）不可宣告**：文件誠實標 `not-run`／peer OS 未跑，與 PRD 硬閘一致；此非「程式邏輯已壞」，而是 **證據閘尚未關閉**。
- 下方 **Important** 項建議在宣稱 production release 前處理或明確寫進 residual risk；**Critical** 無「必須立刻擋死任何使用」的安全漏洞。

---

## Critical（must fix before release claim）

本輪 **未發現** 會使「源端不可變／不呼叫 source CLI／recovered content inert」主不變量失效的 Critical 實作缺陷。

但若要把 **PRD V1 release** 寫成完成，下列是 **claim 層面的硬閘**（非新發現 bug，而是證據仍不足；與 `.omx/ultragoal/*` 一致）：

1. **AC-10 live 36 格**：`docs/host-support.md` 六個 profile 的 Live smoke 皆為 `` `not-run` ``。filesystem packaging ≠ installed-version discovery／activation／request→handoff smoke。
2. **AC-18 dual-OS**：本機僅證明 **Darwin** 閘道；Linux clean-runner 產物未見，不得默認「雙 OS 皆綠」。
3. **獨立 review 閘**：此前 `independent-review-deferred.md` 正確拒絕自批 APPROVE；本報告可作為 dual-review 之一側證據，但 **不** 自動把 live／dual-OS 升成 verified。

> 若有人把 `matrix --json` 的 `"supported": true` 或 `self-check` 的 `matrix.ok` 解讀成「36 格 live 已通過」，即屬 **錯誤 release claim**——見 Important #1。

---

## Important（should fix soon）

### 1. Matrix／self-check 的 `supported` 語意過寬（證據誠實）

- `install/transaction.matrix_report()` 僅檢查：strict frontmatter keys、`resume-<source>` 字樣、36 cells。
- 輸出欄位名為 `"supported": true`，與 PRD AC-10「installed-version-proven」用語易混淆。
- `docs/host-support.md` 與 README 誠實；**機器可讀 matrix 不夠誠實**。
- **建議：** 改為 `packaging_ok`／`evidence_level: verified-filesystem`，或在 matrix 頂層固定附上 `live_smoke: not-run`。

### 2. Reader 邊界把 `E_SQLITE_HOT_JOURNAL` 重映射為 `E_UNSAFE_PATH`（契約／診斷）

實證（fixture `s-cod-11-hot-journal`）：

| 路徑 | code | family |
|---|---|---|
| `codex.ADAPTER.list(...)` | `E_SQLITE_HOT_JOURNAL` | `state_9.sqlite-journal` |
| `scripts/portable-resume`／`reader.run` list | `E_UNSAFE_PATH` | 空 |

原因：`adapter.probe()` → `state=unsafe`，`reader.run` 對 unsafe 一律拋 `E_UNSAFE_PATH`，**丟失** PRD 診斷分類中的 hot-journal 代碼與 family。

- 行為仍 **fail-closed**（exit 6），安全面可接受。
- 自動化／文件若依賴 `E_SQLITE_HOT_JOURNAL` 將在 shipped CLI 上看不到。
- **建議：** probe 攜帶 `error_code`／`family`，或 unsafe 時保留 provider-specific code。

### 3. Install journal recover 未「完成」交易，只做有限還原（AC-12 完整度）

現況優點：

- 相對路徑沙箱（`_safe_rel_path`／`_dest_under_root`）
- backup 必須在 `.portable-resume/` 下才還原
- pending journal 阻擋 install／verify（`E_RECOVERY_REQUIRED`）
- 崩潰後 drift 可被 `verify` 抓到（`E_VERIFY_MISMATCH`）

缺口（對照 PRD「idempotently completes or restores each recorded path」）：

- `recover_root` 對 incomplete journal：**不** 從 stage 繼續 commit，**不** 為 owned replace 保留 preimage（僅 force-with-backup 有 backup）
- 清除 journal 後允許後續 mutation；安全依賴操作者再 `verify`／重裝
- 測試 `test_pending_journal_blocks_mutation_until_recover` 用空 `paths` 模擬，**未** 覆蓋「半提交 owned 檔 + stage 仍在」的完成路徑

**建議：** recover 優先從仍存在且 hash 吻合的 stage 完成 commit；否則還原 owned preimage（journal 記錄）或拒絕清 journal 並要求人工。

### 4. 靜態「無 process」測試可被 `getattr(subprocess, "Popen")` 繞過（測試品質）

- `tests/security/test_isolation.py` 掃描禁止字面量 `subprocess.Popen(`。
- `adapters/codex.py` 可選 zstd 使用 `getattr(subprocess, "Popen")`，註解明示為繞過 foundation static guard。
- zstd 路徑本身設計合理（固定 absolute 路徑、`shell=False`、清空 PATH、timeout、stdout 上限、不跟 source CLI）。
- **問題在測試劇場：** 靜態掃描對「任意 process spawn」不再可靠。
- **建議：** 靜態規則改抓 `subprocess` 使用點 allowlist，或允許 zstd 並單獨測 argv／env 契約（adapter 測試已有部分覆蓋）。

### 5. 源端 immutability 套件覆蓋不完整

- `tests/security/test_source_immutability.py` 只跑 claude／grok／opencode 三源。
- 本輪手動對 codex／cursor／opencode SQLite／CLI fixture 跑 list+show，**位元組／mtime 不變**。
- **建議：** 將六源＋至少一條 SQLite family fixture 納入正式 immutability 套件，避免回歸漏洞。

### 6. 文件缺口（PRD 版面）

- 計劃中的 `SECURITY.md`、`docs/threat-model.md` **不存在**。
- 威脅模型實質散落在 PRD §8 與 handoff-policy；對外 audit 友善度不足。
- `docs/clean-room-attestation.md` 正文仍寫「limited to G001」，而 `docs/provenance.md` 已 attest G001–G004——**attestation 文件宜對齊**。

### 7. Runtime 打包表面偏大（次要攻擊面／體積）

`materialize_plan` 把整個 `portable_resume` 套進 `.portable-resume/runtime/`，包含：

- `install/*`（安裝器）
- `resources/skill/*.tmpl`

skill 執行只需要 reader／adapters／sanitize 等。多拷貝不直接破安全不變量，但擴大 installed root 與審核面。  
**建議：** runtime 白名單拷貝，或明確文件化「故意整包」。

---

## Minor / nits

1. **秘密遮罩 best-effort 缺口（文件已承認）：**  
   - `sk-…`／Bearer／常見 key=value 有遮罩。  
   - Slack `xoxb-…`、PEM `BEGIN PRIVATE KEY` 等未遮罩。README 已聲明非完整 DLP——保持警告即可，可漸進補 pattern。
2. **`test_no_source_cli_exec` PATH shim 主要走 claude list**，未對六 adapter 各跑一遍（另有 static／mock 補強）。
3. **Windows `RootLock` 幾乎是 no-op flock**——V1 目標為 macOS／Linux，可接受；勿默認 Windows 安裝並行安全。
4. **WAL 拷貝上限**使用 `record_bytes`（16 MiB）而非完整 `sqlite_snapshot_bytes`——大 WAL 可能過早 `E_LIMIT_EXCEEDED`；屬保守 fail-closed。
5. **Handoff 對 recovered 指令加 blockquote**，hostile integration 有覆蓋；模型仍可能忽略 banner——產品邊界正確，無法由 library 單獨消弭。
6. **fixture 命名／AC-02：** 六源皆有多組 synthetic fixture（本樹 46 份 `fixture.json`）；concurrent／corrupt／unsupported 多由 adapter 測試＋核心 snapshot 測試承擔，並非每個 source 目錄都有同名 concurrent fixture 檔——可接受但可再對表文件化。

---

## 維度對照摘要

| 維度 | 結論 |
|---|---|
| 1. Security invariants | **通過（決定性）**。無 source CLI；recovered inert／quoted；symlink／FIFO fail-closed；SQLite 私有 copy + query_only；hot journal fail-closed；非 owned collision refuse。 |
| 2. Contract correctness | **大致通過**。v1／request-v1／handoff 界限清楚。診斷碼在 reader 對 unsafe 的重映射為主要契約瑕疵。 |
| 3. Six adapters | **通過（fixture／parser）**。六源皆有 adapter＋synthetic fixtures；unsupported／corrupt／busy／hot-journal 有測試路徑。 |
| 4. Packaging 6×6 | **filesystem 通過**。36 cells、strict `name`+`description`、固定 `run_reader` argv、shared-root conflict 誠實。Live 未跑。 |
| 5. Installer | **基本通過**。dry-run 純淨、verify drift、uninstall claim、force-with-backup。Journal recover 完成語意偏弱（Important #3）。 |
| 6. Evidence honesty | **文件通過；matrix 標籤偏樂觀**（Important #1）。live=`not-run`；dual-OS 未默認。 |
| 7. Clean-room | **政策與測試通過**。禁止 `~/.grok/bundled/skills/**`；synthetic fixture 強制；attestation 文件世代宜對齊。 |
| 8. Test quality | **整體強（146 tests）**，驅動 shipped `reader.run`／install API／scripts。靜態 Popen 掃描與 recover 場景有劇場／缺口風險。 |

---

## What was verified with commands

環境：`Darwin`，`Python 3.14.4`，repo `/Users/iml1s/Documents/mine/resume-skills`。

```text
$ python3 -m compileall -q src scripts tests
compileall_exit=0

$ PYTHONPATH=src python3 -m unittest discover -s tests -q
Ran 146 tests in ~3.8s
OK
unittest_exit=0

$ PYTHONPATH=src python3 scripts/portable-resume --help
help_exit=0
# 六 sources：claude|codex|cursor|opencode|antigravity|grok；actions list|show

$ PYTHONPATH=src python3 scripts/portable-resume self-check --json
selfcheck_exit=0
{"ok":true,"sources":[...6...],"matrix":{"cell_count":36,"expected":36,"ok":true},...}

$ PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
matrix_exit=0
# cell_count=36, expected=36, ok=true；每格 frontmatter_keys=["name","description"]
```

額外抽查（非 brief 必跑，用於判決）：

| 檢查 | 結果 |
|---|---|
| Codex hot-journal via adapter.list | `E_SQLITE_HOT_JOURNAL` |
| 同上 via reader CLI | `E_UNSAFE_PATH` exit 6（仍 fail-closed） |
| codex／cursor／opencode source tree list+show | 位元組／mtime 不變 |
| recover 惡意 `../` rel + 外部 backup | 不寫出 root；`restored_paths=0` |
| recover 後 owned drift | `verify` → `E_VERIFY_MISMATCH` |
| 已安裝 `run_reader`（e2e 套件） | request-v1 + 忽略偽造 `--expected-source` |
| `src` 內 `subprocess.Popen(` 字面量 | 無；存在 `getattr(subprocess,"Popen")` |
| `SECURITY.md` / `docs/threat-model.md` | 不存在 |

閱讀過的主要產物：`README.md`、PRD、host-support／provenance／source-formats、ultragoal 驗證與 deferred 紀錄、`src/portable_resume/**`（paths／snapshot／sanitize／request／handoff／contracts／reader／install／adapters）、`tests/**` 安全／整合／e2e／adapter 結構與代表案例。

---

## Residual risks / honest non-claims

**本報告不宣稱：**

1. 任一 destination host 的 **verified-live** skill 發現／啟動／request→handoff smoke。  
2. **Linux**（或 Windows live）clean-runner 與 macOS 同等通過。  
3. 對真實使用者 session store 的相容性（僅 synthetic fixtures + 結構 probe）。  
4. 完整 DLP／秘密消除。  
5. 電源中斷下整根 skill root 的瞬間原子性（PRD 亦不如此宣稱）。  
6. 宿主模型一定遵守 handoff banner（library 只能做到 quoting + checklist）。  
7. clean-room 的法律證明力——僅有政策、attestation 文字與 repo 結構測試，無第三方 forensic。

**殘餘操作風險：**

- 半完成 install 後若只 `recover` 不 `verify`，可能帶 drift 繼續使用直到下次 verify。  
- 可選 zstd 依賴主機固定路徑二進位；缺失時僅該 provider partial／unavailable。  
- Shared `.agents/skills`（Codex vs Antigravity）需明確分根或 byte-identical body——installer 已 conflict，使用者仍可能手動混裝。

---

## 總結建議

| 目標 | 建議 |
|---|---|
| 合併決定性實作／繼續內部使用 | **可**（本 verdict） |
| 對外 V1 release claim（PRD 全文） | **否**，直到 live smoke 證據、peer OS 產物、Important #1–3 處理或明文降級 claim |
| 下一步最小修復 | (1) matrix 證據欄位改名／標 live not-run (2) reader 保留 hot-journal 診斷碼 (3) recover 完成或硬性保持 journal 至 verify 通過 (4) 補 SECURITY／attestation 對齊 |

**最終一句：**  
安全與契約骨架紮實，測試與 shipped entry points 對得起來，文件對 live／dual-OS 大致誠實；在修正 matrix 語意、CLI 診斷保真、journal recover 完整度之前，適合 **APPROVE WITH MINOR FIXES**，**不** 適合無註記的完整 V1 release 宣告。
