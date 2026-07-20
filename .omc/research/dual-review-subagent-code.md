# Code Review — portable_resume / tests（唯讀）

**Reviewer:** Grok Build subagent (code-reviewer)  
**Scope:** `src/portable_resume/**`、`tests/**`（不改 product code）  
**Date:** 2026-07-20  
**Method:** 全量靜態審閱核心 reader/adapters/sanitize/snapshot/install + 測試劇場與邊界覆蓋；另寫 runner 腳本以利父流程驗證。

---

## Verdict: REQUEST CHANGES

有 **Important 級正確性問題**（ReadBudget 與 `record_bytes` 語意衝突，會讓合法大 session 誤判 `E_LIMIT_EXCEEDED`），以及多處 **test theater / e2e 弱斷言**，會高估「已 ship 路徑已驗證」。不構成安全繞過式 CRITICAL，但不宜在未修前宣告 release-ready。

---

## 驗證命令狀態

| 命令 | 狀態 |
|------|------|
| `python3 -m compileall -q src scripts tests` | **此 subagent 環境無 shell/exec 工具**，無法在本 lane 直接 spawn process。已落地 runner：`.omc/research/_run_review_tests.py`（不碰 product）。 |
| `PYTHONPATH=src python3 -m unittest discover -s tests -v` | 同上。工作樹內存在大量 `*.cpython-314.pyc`，顯示近期曾在 Python 3.14 編譯過 tests，**不能**當作本次 diff 全綠證明。 |
| 建議父流程立刻執行 | 見下方「Required verify commands」 |

**Required verify commands（父流程必須跑完再合成 verdict）：**

```bash
cd /Users/iml1s/Documents/mine/resume-skills
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -v 2>&1 | tail -30
# 或
python3 .omc/research/_run_review_tests.py
# 產出：.omc/research/unittest-tail.txt
```

> 本報告的 REQUEST CHANGES **不**依賴「測試紅燈」；即使全綠，下列 Important 仍成立。

---

## Summary counts

| Severity | Count |
|----------|------:|
| Critical | 0 |
| Important | 6 |
| Minor | 7 |

---

## Critical

（無）

未發現可導致寫入來源 store、執行 source CLI、路徑逃逸讀取、或未標記 untrusted 即當指令執行的確定性漏洞。安全模型整體是 **fail-closed**。

---

## Important

### I-1. `ReadBudget.consume_bytes` 誤用 `normalized_content_bytes` 當「原始讀取」上限

**Severity:** Important  
**Confidence:** HIGH  
**Files:**  
- `src/portable_resume/bounds.py:45-46`  
- `src/portable_resume/snapshot.py:164-221`（`stable_read_bytes` 成功後 `budget.consume_bytes(len(data))`）  
- 所有呼叫 `stable_read_bytes(..., budget=budget)` 的 adapters（claude/codex/cursor/opencode/antigravity/grok）

**Issue:**  
- `Bounds.record_bytes` = 16 MiB（單一 record 可讀上限）  
- `Bounds.normalized_content_bytes` = 8 MiB（輸出正規化總量）  
- 但 `ReadBudget.consume_bytes` 用 **8 MiB** 當 raw `bytes_read` 上限。

後果：

1. 單檔 8–16 MiB 的合法 transcript：filesystem 讀成功 → budget 丟 `E_LIMIT_EXCEEDED`。  
2. `list` 掃多個 session 時 **累加** 全檔大小，忙碌使用者很快爆 budget，即使每個 session 都小於 8 MiB。  
3. Codex zstd 解壓後另 `budget.consume_bytes(len(data))`（`codex.py:345`），與 stable_read 的 raw size 雙重計費。

**Fix suggestion:**  
- 拆 budget：例如 `read_bytes` 上限用 `record_bytes * N` 或 `sqlite_snapshot_bytes`/`scanned_records` 語意，輸出再用 `normalized_content_bytes`。  
- 或明確文件化「讀取總量 ≤ 正規化總量」，並把 `record_bytes` 降到 ≤ 8 MiB 以免契約自相矛盾。  
- 補 unit test：`stable_read_bytes` + budget 對 9 MiB fixture 的期望行為。

---

### I-2. Fixture `expected_code` / `expected_warnings` 只做結構驗證，不做行為 oracle

**Severity:** Important（test theater）  
**Confidence:** HIGH  
**Files:**  
- `tests/helpers/fixture_manifest.py`  
- `tests/fixtures/**/fixture.json`（全部）  
- adapter tests 僅呼叫 `validate_fixture_tree` 計數 / synthetic，**從不**讀 manifest 比對 exit code / warnings

**Issue:**  
每個 fixture 都宣告 `expected_code`、`expected_warnings`、`expected_operation`，但沒有共用 runner 把它們當預期輸出。manifest 欄位可與真實行為脫節而不會紅燈——這是經典 **documentation theater**。

**Fix suggestion:**  
加 `tests/helpers/fixture_runner.py`：對每個 fixture 執行 `reader.run([source, show/list, ... --source-root root])`，assert `rc == expected_code` 且 warnings ⊆ envelope/session warnings。保留現有手寫 edge-case 測試作為補充，而非替代。

---

### I-3. Installed runner e2e 幾乎永遠走 no-match，未鎖定 happy path

**Severity:** Important（test theater / missing e2e）  
**Confidence:** HIGH  
**File:** `tests/e2e/test_installed_runner_and_relocation.py:41-84`

**Issue:**  
- request `cwd` = 臨時 project 的 realpath  
- Claude fixture session `cwd` = `/workspace/project`  
- adapter 以 `same_cwd` 過濾 → **幾乎必然 E_NO_MATCH (3)**  
- 斷言只要求「不 ModuleNotFoundError / Traceback」，成功時才 check `untrusted`；失敗時 `returncode in {3,4,5,6,7}` 過寬

結果：e2e **沒有**證明「安裝後的 `run_reader.py` + request-v1 + fixture show → handoff 內容正確」。

**Fix suggestion:**  
request.cwd 改為 fixture 的 `/workspace/project`（或寫入對齊 fixture 的 temp path），並 hard-assert `returncode == 0`、handoff 含 session 內容與 UNTRUSTED banner。

---

### I-4. Hostile migration 整合測試斷言過軟

**Severity:** Important（test theater）  
**Confidence:** HIGH  
**File:** `tests/integration/test_hostile_context_migration.py:82-87, 124`

```python
self.assertTrue(">" in text or "```" in text or "blockquote" in lower or text.count("rm -rf") >= 1)
self.assertTrue("cwd" in lower or "branch" in lower or ...)
self.assertIn(code, {0, 3, 4, 5, 6, 7})
```

- Handoff 幾乎一定含 `>`（banner / metadata），OR 鏈無法證明 imperative **只**出現在 blockquote。  
- 第二段 checklist 斷言同樣過寬。  
- shell-meta ref 接受幾乎所有非 crash exit code。

對比 `tests/security/test_verifier_regressions.py` / `test_sanitize_handoff.py` 的嚴格「含 token 的行必須 startswith `>`」——那邊才是真防禦測試；integration 層反而變劇場。

**Fix suggestion:**  
對齊 verifier 風格：

```python
lines = [ln for ln in text.splitlines() if "rm -rf" in ln]
self.assertTrue(lines)
self.assertTrue(all(ln.startswith(">") for ln in lines))
```

request-file 案例應 expect 具體 code（通常 3 NO_MATCH），而非大集合。

---

### I-5. Claude：無 title 的 session 在 list 中不可見

**Severity:** Important（正確性 / 缺 edge case）  
**Confidence:** HIGH  
**File:** `src/portable_resume/adapters/claude.py:374-376`

```python
title, branch = _title_and_branch(records)
if title is None:
    return None
```

真實 Claude JSONL 若缺 `customTitle` / `aiTitle` / `summary` / `lastPrompt` / 可抽取 first user，整個 session 被丟棄，`show latest` 可能 `E_NO_MATCH`，即使 transcript 完整。其他 adapter（codex 用 first_user、cursor 可用 transcript user）較寬鬆。

**Fix suggestion:**  
title 允許 `None` 進 list，或 fallback 為 session_id / 截斷 first user（與 codex 對齊）；加 fixture `s-cla-xx-no-title`。

---

### I-6. Grok chunk 合併可暫時突破 per-chunk sanitize 上限

**Severity:** Important  
**Confidence:** MEDIUM–HIGH  
**File:** `src/portable_resume/adapters/grok.py:543-551`

```python
content=prior.content + turn.content,
```

每個 chunk 經 `sanitize_turn_record(..., max_chars=...)`，但相鄰同 role chunk **字串相加**後不再截斷。最終 `reader` 會 `sanitize_session` 再 bound，輸出契約大致守住；但 adapter→reader 中間可持有超大 Turn，list/show 記憶體與時間風險上升。`budget.consume_turns` 只計 turns 數，不計合併後字元。

**Fix suggestion:**  
合併後再跑一次 `sanitize_text` / `_take_utf8`，或禁止無界 concat（只保留 last N chunks）。

---

## Minor

### M-1. 靜態「禁止 subprocess.Popen(」可被 `getattr` 繞過

**Files:**  
- `src/portable_resume/adapters/codex.py:252` `getattr(subprocess, "Popen")`  
- `tests/security/test_isolation.py:72-76` 字串掃描

屬**有意**設計（trusted zstd），但 isolation 測試宣稱 runtime 無 process API 不完整。應用 AST 掃 `subprocess` 屬性存取，或 allowlist codex zstd 並註解。

### M-2. Probe vs list 能力不一致（hot journal）

OpenCode/Codex `probe` 可能 `supported`，`list` 遇 `*-journal` 才 `E_SQLITE_HOT_JOURNAL`。非安全洞，但 UX/診斷不穩定。probe 可試探 family 狀態。

### M-3. `contracts.validate_turn` 未單獨限制 content 長度

只靠 aggregate UTF-8（`contracts.py:144-152`）；schema 有 `maxLength: 8388608`（**字元**）。字元/位元組語意分裂已有部分 equivalence 測試，但 runtime 未 mirror 單欄 maxLength。低風險。

### M-4. Platform peer-OS 文件 gate 過寬

`tests/e2e/test_platform_release_gate.py:70-72`：只要 blob 含 `Linux|macOS|dual-OS|not-run` 即過。應用更硬的 AC-18 句子/欄位檢查（README 其實已寫誠實限制）。

### M-5. `ReadBudget` 記錄數雙重計費

`stable_read_bytes` consume 1 record + parser 每行再 consume → 大 JSONL 提前 `E_LIMIT_EXCEEDED`。建議文件化或只在一層計數。

### M-6. Windows `RootLock` 無 flock

`install/transaction.py:81-84`：`os.name == "nt"` 只 open 不上鎖。跨 process install race。V1 若宣稱 Windows，應註明或用 `msvcrt.locking`。

### M-7. 死碼 / 弱使用面

- `SelectionResult.candidates` 成功路徑幾乎總是空  
- `DiagnosticError(message=...)` 參數被 `__post_init__` 固定覆寫（安全正確，API 易誤導）  
- `snapshot.sha256_file` 標為 test/audit helper（可接受）

Secret redaction 為 best-effort（README 已誠實）—不另升 Important。

---

## 正面觀察（應保留）

1. **安全邊界清楚**：request-v1 當 data 非 argv；diagnostic 固定英文、不洩漏 recovered text；handoff 全 blockquote + checklist。  
2. **SQLite 私有快照**：`mode=ro&cache=private` + `PRAGMA query_only=ON` 再驗證；SHM 只監看不複製；hot journal fail-closed。  
3. **stable_read**：雙讀 + parent membership fingerprint，並有 same-stat spoof / post-verify mutation 回歸（`test_snapshot` / `test_verifier_regressions`）。  
4. **Sanitize pipeline 雙層**：adapter 出 Turn + reader `sanitize_session` 再政策化，避免 provider 分歧。  
5. **Contract ↔ JSON Schema 共享 corpus**（含 aggregate UTF-8 extension）是高品質做法。  
6. **Adapter fixture 覆蓋面實在**：parent/fork chain、compaction、thinking/signature、partial tail、zstd PATH 隔離、archive exact-id、orphan parts、stale index 等—多數**不是**空殼 assert。  
7. **Installer**：36-cell matrix、dry-run 純觀測、衝突 refuse、force+backup、verify drift—交易語意清楚。  
8. **Provenance / clean-room 文件 gate** 與「不得讀 `~/.grok/bundled`」靜態檢查到位。

---

## 邏輯 / 錯誤處理速查

| 區域 | 評估 |
|------|------|
| `select_session` latest / exact id / abs path / text / ambiguous | 正確；path 需 approved_roots；ties 穩定 |
| `AmbiguousSelection` / `E_NO_MATCH` 雙通道 stdout+stderr | 有意設計，有測試 |
| Adapter 未知 schema | 多為 fail-closed（codex/cursor/opencode） |
| Reader 未預期 Exception | 收斂 `E_INVARIANT`，不噴 traceback |
| Source immutability | 有 fingerprint 測試（部分 source） |
| 大檔 / 多檔 list | **弱**（見 I-1） |
| Claude 無 title | **弱**（見 I-5） |

---

## 殘餘風險

1. **真實 host store 格式漂移**：fixtures 是 clean-room 合成；live smoke 文件已標 `not-run`——不可把 fixture 綠燈當 live 相容證明。  
2. **Linux peer gate 未跑**（`.omc/research/linux-gate-report.md`）：不可宣稱 dual-OS AC-18。  
3. **Secret redaction 非 DLP**。  
4. **zstd 依賴 trusted 絕對路徑**；PATH shim 測得正確，但平台未裝 zstd 時僅 partial。  
5. 本 lane **未執行** unittest；合成最終 release 前必須有父流程綠燈證據。

---

## 建議優先序

1. 修 **I-1 ReadBudget**（契約自洽 + 防誤殺大 session）  
2. 修 **I-3 e2e cwd** 與 **I-4 hostile 斷言**（消除假綠）  
3. 加 **I-2 fixture oracle runner**  
4. 修 **I-5 Claude title**、**I-6 Grok concat**  
5. Minor 靜態 isolation / probe 一致性

---

## Recommendation

**REQUEST CHANGES**

在 I-1 與至少一項 test-theater（I-2 或 I-3/I-4）處理前，不建議 APPROVE 為 release-ready。安全核心設計品質高，問題集中在 **資源邊界語意** 與 **測試是否真的鎖住行為**。

---

## Open Questions

1. `ReadBudget` 綁 8 MiB 是否為有意「讀取量 = 輸出量」政策？若是，應同步下修 `record_bytes` 並寫進 docs/bounds。  
2. Fixture manifest 的 `expected_*` 是給未來 runner 還是僅供人讀？現況會誤導 reviewer。  
3. Claude 無 title 不可見是否為產品決策？

---

*本報告為唯讀審查；product code 無修改。輔助檔：`.omc/research/_run_review_tests.py`（測試 runner，非 product）。*
