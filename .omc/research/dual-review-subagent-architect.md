# Architect / Critic 審查：Portable Resume Skills V1

**角色：** 唯讀 architecture/code critic（非實作）  
**日期：** 2026-07-20  
**範圍：** PRD / ADR / install·adapters 設計與實作對照；焦點 = 6×6 packaging 誠實度、installer claim/journal 模型、adapter protocol、evidence levels（live not-run）、AC-10/AC-18 缺口  
**模式：** THOROUGH → 因發現 ≥3 項 Important + release-blocker 類缺口，後半段以 ADVERSARIAL 壓力測試 claim 誠實度  
**產品碼修改：** 無（本審查不寫 product code）

---

## Verdict

**REQUEST CHANGES**

（僅就「deterministic packaging / fixture bar」可接受；就 PRD 原文定義的 **V1 release claim（AC-10 36 installed-version cells + AC-12 journal recovery 語義 + AC-18 dual-OS）** 不可批准。）

---

## Overall Assessment

共享 Python core + 六 source adapters + 六 destination materialize skills 的主架構對齊 spec，且 **文件層（README / host-support / provenance）對 live smoke 與 peer OS 大多誠實**。  
但機器可讀 `matrix --json` 用 `supported: true` / `ok: true` 表述 **僅 frontmatter render 通過的 36 cells**，與 PRD AC-10 的 installed-version 定義衝突；installer journal **未在 commit 中途持久化 path 狀態**，`recover_root` 可在 mixed state 下清除 journal 並回 `ok`；AC-18 Linux gate **未跑**。  
這些不是風格偏好：它們直接削弱「完成 V1」與「AC-12 可恢復」的可證偽性。

---

## Pre-commitment Predictions → Actual

| # | 預測最可能問題 | 實際結果 |
|---|---|---|
| 1 | 6×6 `supported` 與 live `not-run` 混用 | **確認**：`matrix_report` 僅以 frontmatter 判定 `supported` |
| 2 | claim/journal 未達 PRD 的 durable recovery | **確認**：path state 不中途落盤；recover 可「清 journal 留 mixed」 |
| 3 | AC-10 被 filesystem packaging 偷換成 release pass | **確認**：prd-verification 寫 pass(filesystem)；live UI activation not-run |
| 4 | AC-18 dual-OS 紙上通過 | **確認**：linux-gate docker daemon 不可用，NOT RUN |
| 5 | installed-runner e2e 過軟 | **確認**：fixture cwd 不匹配時接受 no-match / 非 0 也算過 |

---

## Critical（必須在「V1 release claim」前處理）

### C1. AC-10：36/36 **installed-version-proven** cells 未達 PRD 原文，但 packaging 報告像已完成

**Evidence**
- PRD AC-10：``V1 requires 36/36 **supported**, installed-version-proven cells covering discovery, documented activation, labeled protocol, resource resolution/invocation, and this runtime's deterministic handoff. `partial`, `unsupported`, or mock-only cells do not satisfy completion.``（`.omx/plans/prd-portable-resume-skills.md` §11）
- `matrix_report()`（`src/portable_resume/install/transaction.py:459-482`）把 `supported` 設成：

```python
"supported": keys == ["name", "description"] and f"resume-{source}" in text,
```

  亦即 **render/frontmatter 成功即 supported**。
- `docs/host-support.md` 六列 Live smoke 全是 ``not-run``。
- `.omc/research/live-smoke-report.md` 證明：install/verify + **fixture handoff runner** 有跑；但明確寫  
  ``Full interactive host skill picker activation: **not-run**``。

**Why this matters**  
若對外或 self-check 以 `matrix ok:true / cell_count:36` 當作 AC-10 完成，會把「包裝生成」偷換成「主機 installed-version 啟用鏈」。Architect 迭代 3 / Critic plan 審查已把這條當 release stop rule。

**Fix（actionable）**
1. 拆分 matrix 欄位：至少 `packaging_ok` vs `live_activation` vs `evidence_level`；**禁止** packaging 通過就輸出 `supported: true`。
2. `self-check` / `matrix --json` 在任何 live cell 為 `not-run` 時，`release_ready: false`（或獨立 `v1_release_ok: false`），並附 `W_LIVE_SMOKE_NOT_RUN`。
3. 更新 `docs/host-support.md` 分欄：filesystem packaging / installed-runtime smoke / host UI activation。
4. 在宣稱 AC-10 前，為每 host 至少一 skill 留下：discovery → activation 文法 → request-v1 寫入 → fixed argv → handoff 的 **installed-version 證據**（或正式降級 scope，改 PRD）。

**Confidence:** HIGH  
**Realist:** 最壞情況是錯誤 release 宣稱；文件已部分誠實，但 **CLI machine contract 仍會誤導自動化**。不降級。

---

### C2. AC-18：Linux clean-runner **未執行**，不得 dual-OS release

**Evidence**
- PRD AC-18：fresh suites 在 **macOS 與 Linux clean runners** 皆 green；缺任一 OS gate 阻擋 V1 release claim。
- `.omc/research/linux-gate-report.md`：  
  ``docker daemon unavailable`` → ``Linux deterministic gate **NOT RUN / FAILED TO START**`` →  
  ``Do **not** claim AC-18 dual-OS release.``
- `tests/e2e/test_platform_release_gate.py:64-75` 的 peer-OS 測試只檢查 README/host-support **字串**含 Linux/macOS/not-run，**不驗證第二個 OS 實際跑過**。

**Why this matters**  
路徑/fcntl/lock/permission 在 Linux 上的差異正是 AC-18 存在理由。字串誠實 ≠ gate 完成。

**Fix**
1. 在 Linux runner/container 跑 PRD §13 完整指令集，原始輸出依 OS 歸檔。
2. platform gate 改為讀取 **peer evidence artifact**（或明確 `AC18_PEER_STATUS=missing` fail 在 release profile），而非只掃 docs 字串。
3. 在 artifact 未齊前，任何 release checklist 必須硬擋。

**Confidence:** HIGH  

---

### C3. Installer journal / recover 語義未達 PRD AC-12（可清除保護、留下 mixed state）

**Evidence（code）**
1. **commit 中途 path state 只在記憶體更新，不落盤**（`transaction.py:274-283`）：  
   loop 內 `journal["paths"][rel]["state"] = "committed"` 後**沒有** `_write_journal`；只有全部 replace 完才寫 `complete`。crash 時 durable journal 仍是 `committing` + 幾乎全是 `staged`。
2. **staging 期間無 durable journal**（journal 在 `state="committing"` 才第一次 `_write_journal`，L271-272）。與 PRD「stage 完整後寫 durable journal 再 replace」部分對齊，但 commit 進度不可恢復。
3. **owned replace 不做 backup**（`plan.backups` 只含 non-owned force 路徑，L203-207）。  
   mid-commit exception 的 `_attempt_rollback`（L304-323）對 owned replace **無法還原舊 bytes**。
4. **`recover_root` 不 complete、不 fail-closed**（L326-349）：  
   - 僅在有 `backup` 時還原；  
   - `shutil.rmtree(stage_dir)` **丟掉仍可用的 staged 新檔**；  
   - 然後 **`os.remove(journal)`** 並回 `{"ok": True, "action": "restored_from_journal"}`。  
   結果：`E_RECOVERY_REQUIRED` 保護消失，tree 可能 mixed，需靠事後 `verify` 才發現。
5. **無 fsync**（journal/manifest/dir）：PRD 要求 journal fsync 與 directory fsync；實作僅 `write + os.replace`。
6. **測試劇場風險**：`tests/integration/test_installer_transaction.py:42-78` 注入 **空 paths** 的 synthetic journal，不覆蓋「半數 owned 檔已 os.replace」真實 crash。

**Why this matters**  
PRD/ADR 明確：crash 非瞬間原子，但 journal 必須使 mixed 可偵測，且 recover **idempotently complete or restore**；unrecoverable drift **fail closed**。現狀是 recover 可「成功」清掉偵測訊號。

**Fix**
1. 每個 path commit 後更新 journal（至少每 N 檔 + 最終）並 fsync。
2. 對所有將被 replace 的既有檔（含 owned）在 commit 前記錄 backup 或 content hash+rollback 來源。
3. `recover_root`：  
   - 若 stage 完整且 generation 可 CAS → **完成 commit + manifest-last**；  
   - 否則 restore backups / 刪 creates；  
   - 驗證後再清 journal；  
   - 無法證明一致 → 保留 journal + `E_RECOVERY_REQUIRED` / `E_VERIFY_MISMATCH`，**禁止 ok:true**。
4. 新增 fault-injection：mid-commit kill 後 recover + verify 的精確期望（INS-008/017 等級）。

**Confidence:** HIGH  
**Realist：** 非 source-store 損毀；destination skill root 可 reinstall。但 **AC-12 的可恢復宣稱目前過度**——維持 Critical（release claim / AC-12 誠實度），不是「小瑕疵」。

---

## Important（應盡快修，否則造成重大返工或誤判）

### I1. `matrix` / `self-check` 證據模型過窄

- `self_check`（`reader.py:133-171`）只檢查 adapter import + matrix cell_count==36 + schema 檔存在。  
- 不輸出 host evidence_level、live not-run、OS peer status。  
- `HostProfile.evidence_level` 預設 `verified-filesystem`（`catalog.py:24`）但未進入 matrix JSON。

**Fix：** self-check schema 增加 `packaging` / `live` / `platforms` 三區；release gate 讀 `v1_release_ok`。

### I2. Generation CAS 在 lock 外規劃，競態下可丟 claim

- `plan_install` 在 lock 外讀 generation 並 build manifest（`transaction.py:149-222`）。  
- `execute_install` 在 lock 內只做寬鬆 generation 檢查（L237-242），**不重算 plan / 不重讀 claims**。  
- 兩並行 install 可同時 plan 同一 `generation+1`；後者可能覆蓋或衝突處理不足。

**Fix：** 在 `RootLock` 內 re-load manifest → re-plan → stage → commit；generation 比較失敗重試一次。

### I3. Uninstall 無 journal

- `uninstall_claim`（L397-445）在 lock 下直接刪檔改 manifest，無 durable journal。  
- crash 可留下「claim 半刪 / 檔半刪」且 **無 E_RECOVERY_REQUIRED**。

**Fix：** uninstall 走與 install 相同 journal 協議（claim removal + refcount delete）。

### I4. Shared-root concurrent claim 測試不足

- `test_uninstall_preserves_unrelated_claim_on_shared_explicit_root` 名稱寫 shared，實為 **兩個不同 root**（`test_installer_transaction.py:100-109`）。  
- 真正同一 root 多 claim（byte-identical 共享）與 concurrent install 未覆蓋 INS-007/013。

**Fix：** 補 byte-identical dual-claim 與 concurrent lock 測試；或改名避免劇場。

### I5. Installed runner e2e 過軟

- `test_installed_runner_and_relocation.py:77-84`：cwd 不匹配 fixture 時允許 no-match；只要沒 Traceback 就過。  
- 未強制「安裝後 runtime 對 fixture 必出 handoff 成功」。

**Fix：** 用 fixture 內真實 cwd（或改 fixture cwd 為 temp project）**要求 exit 0 + untrusted banner**。  
（`.omc/research/live-smoke-report.md` 顯示另一條 runner 已能 exit 0——應把該路徑固化進 unittest。）

### I6. AC-12 在 prd-verification 標 **pass** 過度

- `.omx/ultragoal/prd-verification.md` AC-12 = pass，但對照 C3，應標 **partial / journal recovery incomplete**。

**Fix：** 更新 verification 文件，避免下游把 incomplete recovery 當綠燈。

### I7. SQLite WAL copy 被 `record_bytes`（16 MiB）間接封頂

- `snapshot.py:321-326`：WAL 使用 `min(bounds.record_bytes, remaining)`。  
- 聚合預算是 256 MiB，但單一 WAL >16 MiB 會失敗，可能過度 fail-closed。

**Fix：** WAL 使用剩餘 `sqlite_snapshot_bytes` 預算，而非 `record_bytes`。

---

## Minor / nits

1. PRD/ADR 檔頭仍寫 “Initial Ralplan draft / pending re-review”，與已 approve 的 architect/critic plan 審查不一致（文件 hygiene）。
2. Journey 範例仍用 slash/flag 簡寫；README 已用 labeled protocol——保持後者。
3. `test_security.test_isolation` 靜態掃描 `subprocess.run(` 字串：目前 runtime 無，但 zstd optional path 未來若加入需白名單例外。
4. platform peer 測試的「not claim both OS」字串断言極易被文案改寫繞過。
5. Codex/Antigravity 共用 `.agents/skills` 衝突有測且文件誠實——**這點是好的**。
6. Adapter `SourceAdapter` Protocol（probe/list/show + CapabilityReport states）與 reader 共享 sanitizer/envelope——**結構健康**。

---

## Focus area deep dive

### 1) 6×6 packaging honesty

| 層 | 狀態 | 誠實？ |
|---|---|---|
| 36 unique (host,source) materialize | 有：catalog + render + tests | 是 |
| 嚴格 `name`+`description` frontmatter | 有：render + verify | 是 |
| fixed `run_reader.py` argv / request-v1 指示 | 有：SKILL.md.tmpl + request.py | 是 |
| shared-root 非 byte-identical → conflict | 有：codex vs antigravity test + host-support | 是 |
| CLI `supported` / `ok` = full AC-10 | **否** | **否——主要誠實破口** |
| Live UI activation | not-run（文件） | 文件是；CLI 否 |

### 2) Installer claim / journal model

| 能力 | 實作 | 對 PRD |
|---|---|---|
| claim key `(host\|scope\|root)` | 有 | 對 |
| per-file claim refs + hash | 有 | 對 |
| non-owned refuse / force-with-backup | 有 | 對 |
| dry-run purity | 有 | 對 |
| root flock | 有（POSIX） | 對 |
| generation 單調 | 有，但 CAS 弱 | 部分 |
| durable journal + path progress | **弱** | **未達** |
| recover complete-or-restore fail-closed | **未達** | **未達** |
| fsync | **無** | **未達** |
| uninstall journal | **無** | **未達** |

### 3) Adapter protocol

- `adapters/base.py`：`SourceAdapter` Protocol + `CapabilityReport` states closed set — **合格**。
- Reader 擁有 envelope / inert / selection / diagnostics；adapters 回 typed records — **符合 one contract, thin edges**。
- 六 adapters 皆 export `ADAPTER`；fixture 矩陣涵蓋 supported/corrupt/unsupported/hot-journal 等 — **結構可接受**。
- 未發現 source CLI 呼叫路徑；isolation + immutability 測試存在 — **安全邊界主幹成立**。

### 4) Evidence levels（live not-run）

- `docs/host-support.md` 定義 `verified-live | verified-filesystem | partial | unsupported | not-run` — **好**。
- 表格 Live 全 `not-run`；provenance 明確不 claim dual-OS / live activation — **文件誠實**。
- `W_LIVE_SMOKE_NOT_RUN` 在 diagnostics/schema 存在，但 **matrix/self-check 不發出** — **執行面缺口**。
- live-smoke harness 把 packaging+runner 與 UI activation 分開 — **方向正確**，應回寫 host-support 分欄並驅動 release gate。

### 5) AC-10 / AC-18 gaps（對照表）

| AC | PRD 要求 | 現況 | 可否 claim V1 complete |
|---|---|---|---|
| AC-10 | 36 installed-version 全鏈 | packaging 36 + runner smoke；**UI activation not-run** | **否** |
| AC-11 | request-v1 + fixed argv | 模板 + unit + runner **大致是** | 條件式是 |
| AC-12 | journal recover 等 | dry-run/install/verify/uninstall 有；**recover 語義不足** | **否（誠實標 partial）** |
| AC-14 | 分級 evidence | 文件有；CLI 混用 supported | 文件是 / 機器否 |
| AC-18 | macOS + Linux | macOS 有紀錄；**Linux NOT RUN** | **否** |
| AC-19 | Windows 分列 | 誠實 non-blocker | 是 |

---

## Multi-Perspective Notes

### Security
- Source isolation / inert handoff / request no-symlink / private SQLite URI+query_only：**主幹扎實**。
- 風險在 **destination installer recovery** 與 **錯誤 capability 宣稱**，不是 source mutation。
- Optional zstd 路徑需維持 fixed-argv（已有 fixture 方向）。

### New-hire / Executor
- 看到 `matrix --json` 的 `ok:true` 很容易以為 36 cells 已 live 驗證。
- recover 文件若寫「跑 recover 即可」會誤導：現在 recover 可能只是刪 journal。

### Ops / Skeptic
- 無 Linux artifact 就 ship，等於把 fcntl/path 差異賭在單一 Darwin 上。
- 電源中斷 mid-upgrade 後，自動化若只跑 recover 不跑 verify，可能帶著 mixed skills 繼續。

---

## Key Assumptions（抽樣評級）

| 假設 | 評級 |
|---|---|
| 36 packaging cells = 使用者可在六 host 啟用 | **FRAGILE**（model-mediated + not-run） |
| journal recover 滿足 AC-12 | **FRAGILE**（code 反證） |
| docs 誠實 ⇒ CLI/自動化也誠實 | **FRAGILE** |
| dual-OS 可之後補 | **REASONABLE**（但阻擋 release claim） |
| adapter protocol 穩定 | **VERIFIED** |
| clean-room 未吃 installed grok bundle | **REASONABLE**（政策+靜態測試；非密碼學證明） |

---

## Pre-mortem（若依現狀宣告 V1 complete 會怎麼爆）

1. 使用者在 OpenCode/Antigravity 用自然語言叫不到 skill → 怪「36 supported」。  
2. Linux 路徑/`O_NOFOLLOW` 差異在 CI 外才爆。  
3. 升級 install 被 kill → recover 後 skills 半新半舊，agent 行為怪異。  
4. 並行 global install 丟 claim / 覆蓋 generation。  
5. 自動化 release 只看 `self-check ok` 綠燈出包。  
6. 把 fixture handoff 當成 host UI activation 證據，日後 format drift 無 early signal。

---

## What was verified

### 本審查直接驗證（靜態 + 既有 artifact）
- 完整閱讀：PRD、ADR、spec 摘要、test-spec 關鍵章節、architect-iter3、plan critic、host-support、provenance、source-formats、README。
- 完整追蹤：`install/{catalog,manifest,transaction,cli,render}.py`、`adapters/base.py`、`reader.py`、`request.py`、`snapshot.py`（穩定讀/SQLite）、skill templates、integration/e2e/security 關鍵測試。
- 既有命令證據（ultragoal / research，非本 agent 重跑 shell——本 critic lane 無 Bash tool；以落盤證據交叉驗證）：

| 命令 / 證據 | 結果 |
|---|---|
| `unittest discover -s tests` | **145 tests OK**（`.omx/ultragoal/prd-verification.md`） |
| `self-check --json` | exit 0，`ok:true`，matrix 36 |
| `matrix --json` | exit 0，`ok:true`，`cell_count:36` |
| install lifecycle / drift / uninstall | 綠（同 verification doc） |
| Linux gate | **NOT RUN**（`.omc/research/linux-gate-report.md`） |
| Live smoke | packaging+runner PASS；**UI activation not-run**（`.omc/research/live-smoke-report.md`） |

### 本審查**未能**在此 turn 重新 spawn 的指令
- 即時 `python3 -m unittest discover -s tests -q` 重跑（工具面無 shell）。  
  以上以 2026-07-20 落盤 verification + 原始碼一致性審查代替；合併前建議 orchestrator **再跑一次**使用者指定三條命令並貼 raw 輸出。

---

## Residual risks / honest non-claims

**可以誠實宣稱的：**
- deterministic / fixture-backed reader + 六 adapters；
- 36-cell **filesystem packaging** 與 strict frontmatter；
- request-v1 邊界與 inert handoff 契約；
- install dry-run / conflict refuse / verify drift / 基本 claim uninstall；
- clean-room 政策與 synthetic fixtures；
- live UI activation = **not-run**；Linux AC-18 = **not-run**。

**不可以宣稱的：**
- V1 release complete per AC-10/AC-18 原文；
- 36 cells `supported` 於 installed-host activation 意義；
- installer crash recovery 已達 PRD 的 complete-or-restore + fail-closed；
- dual-OS green；
- independent dual-review 已 APPROVE（仍 deferred）。

---

## 建議後續（給 planner/executor，不在本 turn 改碼）

1. **先修 C3 journal/recover**（否則 AC-12 不能綠）。  
2. **改 matrix/self-check 證據模型**（C1/I1）——低成本、高誠實度。  
3. 跑 Linux gate artifact（C2）。  
4. 固化 installed-runtime handoff e2e（I5）；UI activation 另列 evidence。  
5. 更新 prd-verification AC-12/AC-10 標籤為 partial，直到上述完成。  
6. 再進 dual-review / verifier，**禁止**用 packaging `ok:true` 當 release 唯一綠燈。

---

## Verdict Justification

- **不 REJECT：** 核心安全模型、adapter 協議、packaging 主幹、文件 live/OS 誠實敘述多數成立；不是全面失敗。  
- **不 APPROVE / APPROVE WITH MINOR FIXES：** C1–C3 直接阻擋 PRD 定義的 V1 release claim；其中 journal 是實作缺陷而非僅缺證據。  
- **REQUEST CHANGES：** 修 journal+evidence machine contract，並補 AC-18 / 誠實 AC-10 分級後，可再審 **APPROVE WITH MINOR FIXES** 或在降級 scope 下批准 deterministic bar。

**Escalation:** ADVERSARIAL（因 AC 誠實度 + installer recovery 系統性缺口）。  
**Realist recalibrations:** 無 Critical 因「理論最大傷害」而降級；journal 維持 Critical 是因 **AC-12 宣稱與實作矛盾**，不是 source 資料遺失。

---

## Open Questions

1. 產品是否正式降級 V1 範圍為「deterministic packaging bar」，把 live activation / dual-OS 移到 V1.1？若是，應改 PRD AC-10/18 原文，而非只在 README 加 limitations。  
2. live-smoke 的 installed-runtime handoff 是否應升級 host-support 的某一欄（仍非 verified-live UI）？  
3. 是否需要在 CI 強制 docker-linux job，還是接受外部 Linux runner 手動 artifact？

---

*Ralplan-style summary row*
- Principle/Option Consistency: **Pass**（Option A + fail-closed 原則仍在）
- Alternatives Depth: n/a（實作審查，非新 ralplan）
- Risk/Verification Rigor: **Fail**（matrix supported、AC-12 recover、AC-18 peer 測試過弱）
- Evidence honesty (docs): **Pass-with-caveat**
- Evidence honesty (CLI/automation): **Fail**

**Hand-off:** planner（調整 AC/證據模型與 release gate）→ executor（journal + matrix schema）→ verifier（重跑三條命令 + Linux artifact）  
**本檔 verdict：REQUEST CHANGES**
