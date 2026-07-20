# 代碼審查報告：portable-resume-skills V1 (唯讀審查)

**審查日期：** 2026-07-20  
**目標專案：** `/Users/iml1s/Documents/mine/resume-skills` (Working Tree)  
**審查工具：** Antigravity CLI  
**輸出路徑：** `/Users/iml1s/Documents/mine/resume-skills/.omc/research/dual-review-agy.md`

---

## 1. 審查結論 (Verdict)

**結論：APPROVE WITH MINOR FIXES (建議在修正單元測試問題後發布)**

在檔案系統、安全防禦隔離機制、雙向適配器 (Adapters) 設計與事務型安裝器 (Installer) 上，專案的設計與實作皆具有極高的健壯性，完全符合 PRD 描述的 Clean-Room 安全隔離與防禦性原則。
唯目前 working tree 中的一個關鍵單元測試存在 bug，導致 `unittest` 無法以 100% Green 的狀態通過，此點會阻礙 AC-18 要求的 Release 宣稱，必須在發版前修復。

---

## 2. 關鍵修正項目 (Critical - 發版前必須修復)

### 2.1 單元測試 `test_u018_one_over_each_budget_fails` 失敗
*   **檔案路徑：** [test_model_contracts.py](file:///Users/iml1s/Documents/mine/resume-skills/tests/unit/test_model_contracts.py#L104-L109)
*   **錯誤現象：** 
    執行單元測試時拋出：
    ```
    FAIL: test_u018_one_over_each_budget_fails (method='consume_bytes')
    AssertionError: DiagnosticError not raised
    ```
    隨後因 `caught.exception` 屬性不存在而拋出 `AttributeError`。
*   **根本原因分析：**
    在 [bounds.py](file:///Users/iml1s/Documents/mine/resume-skills/src/portable_resume/bounds.py#L45-L49) 中，`ReadBudget.consume_bytes` 的實作如下：
    ```python
    def consume_bytes(self, amount: int) -> None:
        self._consume("bytes_read", amount, self.limits.sqlite_snapshot_bytes)
    ```
    其消耗的限制額度為 `self.limits.sqlite_snapshot_bytes`。
    然而，在單元測試 `test_u018_one_over_each_budget_fails` 中建立測試用的 `Bounds` 時：
    ```python
    budget = ReadBudget(Bounds(scanned_records=0, normalized_content_bytes=0, normalized_turns=0))
    ```
    並未傳入 `sqlite_snapshot_bytes` 參數，因此該限制額度沿用了 `Bounds` 類別的預設值 `256 * 1024 * 1024` (256 MiB)。
    當呼叫 `budget.consume_bytes(1)` 時，由於 `1` 小於預設的 256 MiB 限制，`_consume` 未拋出 `DiagnosticError.limit_exceeded()`，導致測試的 `assertRaises(DiagnosticError)` 失敗。
*   **修復建議：**
    修改測試，在初始化 `Bounds` 時將 `sqlite_snapshot_bytes` 也明確設為 `0`：
    ```python
    budget = ReadBudget(Bounds(scanned_records=0, normalized_content_bytes=0, normalized_turns=0, sqlite_snapshot_bytes=0))
    ```

---

## 3. 重要改進建議 (Important)

### 3.1 共享專案根路徑衝突指引
*   **說明：** `codex` 和 `antigravity` 的 project-scope 預設路徑皆為 `.agents/skills`。如果用戶在同一個專案根目錄下同時為這兩個 Host 安裝 project-scope，將觸發 `E_INSTALL_CONFLICT`。
*   **建議：** 雖然在 `README.md` 與 `docs/host-support.md` 已有詳細說明，但建議在安裝 CLI 的衝突錯誤輸出中，提供更明確的指示，引導用戶使用自訂的 `--root` 參數。

---

## 4. 次要項目與微調 (Minor / Nits)

### 4.1 診斷訊息的細緻化 (以安全為前提)
*   `diagnostics.py` 中 `_DEFAULT_MESSAGES` 將 `E_LIMIT_EXCEEDED` 統一定義為 `"A configured resource bound was exceeded."`。這種與具體內容無關的設計極佳地防止了敏感資訊洩漏，若未來有需要，可在 `stderr` 的 `family` 欄位中添加安全的 basename 提示，以提升除錯效率。

---

## 5. 指令驗證記錄 (Verification)

審查過程中於 `/Users/iml1s/Documents/mine/resume-skills` 執行了以下驗證指令：

1.  **Python 語法與編譯驗證：**
    ```bash
    python3 -m compileall -q src scripts tests
    ```
    *   **結果：** 成功（Exit Code 0，無任何語法錯誤）。

2.  **執行單元測試：**
    ```bash
    PYTHONPATH=src python3 -m unittest discover -s tests
    ```
    *   **結果：** 失敗（Exit Code 1，145 個測試中，有 1 個 FAIL，1 個 ERROR，錯誤詳見第 2 節描述）。

3.  **CLI Help 驗證：**
    ```bash
    PYTHONPATH=src python3 scripts/portable-resume --help
    ```
    *   **結果：** 成功（Exit Code 0，成功列印使用手冊與可用的 positional arguments）。

4.  **適配器與 CLI 自檢 (Self Check)：**
    ```bash
    PYTHONPATH=src python3 scripts/portable-resume self-check --json
    ```
    *   **結果：** 成功（Exit Code 0，輸出如下）：
        ```json
        {"actions":["list","show"],"adapters":{"antigravity":{"key":"antigravity","ok":true},"claude":{"key":"claude","ok":true},"codex":{"key":"codex","ok":true},"cursor":{"key":"cursor","ok":true},"grok":{"key":"grok","ok":true},"opencode":{"key":"opencode","ok":true}},"matrix":{"cell_count":36,"expected":36,"ok":true},"ok":true,"schema_version":"portable-resume/self-check-v1","sources":["antigravity","claude","codex", "cursor","grok","opencode"],"warnings":[]}
        ```

5.  **Host 與 Source 36 Cell 矩陣驗證：**
    ```bash
    PYTHONPATH=src python3 scripts/install-resume-skills matrix --json
    ```
    *   **結果：** 成功（Exit Code 0，回傳包含 36 個 cell 的完整 JSON，證實 6 Host × 6 Source 檔案系統層級的 packaging_supported 均為 `true`）。

---

## 6. 殘留風險與誠實聲明 (Residual Risks & Honest Non-claims)

根據 PRD 與實際程式碼審查，本專案誠實地保留並確立了以下邊界：

*   **非程序還原：** 本專案僅提供**靜態上下文遷移** (handoff/migrate)，不涉及且不支持任何活體 Host Agent Process/Session 的現場恢復。
*   **Host Live Smoke 為 `not-run`：** 所有 Host 的 `live_supported` 在現階段皆為 `false`，且 `live_evidence` 標記為 `not-run`。這真實反應了目前並無實際 Host App 發行版在測試環境中被實地執行驗證，此 36-cell 矩陣是基於**檔案系統層次** (filesystem-level) 的正確性所做的驗證。
*   **跨平台 release 限制 (AC-18)：** 目前僅在 macOS (Darwin) 環境執行了驗證。對於 Linux 與 Windows 環境，維持 `not-run` 且不虛報的誠實立場。
*   **SQLite 併發寫入與未決日誌拒絕：** 對於帶有 rollback journal 或是 concurrent mutation 的 SQLite 資料庫，適配器會主動 Fail Closed 並拋出 `E_SQLITE_HOT_JOURNAL` 或 `E_SOURCE_BUSY`。
*   **敏感資訊過濾限制：** 敏感資訊過濾 (Sanitizer) 採用正則表達式，為最佳努力的 DLP 移除 (Best-effort)，不保證 100% 的絕對阻斷，使用者在分享 handoff markdown時仍需自行審查。
