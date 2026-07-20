# Dual-Review 報告 — Claude Fable 5 seat（portable-resume-skills V1 全樹）

- 審查者：Claude Fable 5（獨立 read-only review seat）
- 日期：2026-07-20
- 範圍：`/Users/iml1s/Documents/mine/resume-skills` working tree（main、無 commit）；依 `.omc/research/dual-review-brief-safe.md` 八個維度全覆蓋
- 方式：全量閱讀 `src/portable_resume/**`（含六個 adapters、installer、resources 模板）、`tests/**`（unit/adapters/security/integration/e2e）、`scripts/*`、`docs/*`、PRD 與 ultragoal 驗證文件；實際執行 brief 指定的全部驗證指令，另外自行做了三組對抗性實機驗證（installer 生命週期、drifted-owned reinstall、uninstall 殘留）。

---

## Verdict: **APPROVE WITH MINOR FIXES**

決定性（deterministic）V1 bar 誠實達成：145 個測試全綠、36-cell packaging matrix 正確且 live 欄位誠實標 `not-run`、六個 adapter 的 fail-closed 紀律一致、request-v1 邊界與 handoff 引用防護經對抗性測試證明有效、clean-room 文件與掃描到位。未發現 Critical 級安全缺陷。

但我以實機驗證找到 **3 個 Important**（installer 強健性與 PRD 規範文字的落差，其中一項會無備份地銷毀使用者對 owned 檔案的本地修改）與若干 Minor。這些不推翻目前「deterministic bar pass、live/dual-OS 誠實未宣稱」的狀態（release 本來就被 live smoke 與 AC-18 擋住），但應在正式 release claim 引用 AC-12 / PRD §7.3 之前修復。

---

## Critical（release claim 前必修）

**無。**

未發現：source CLI 被喚起的路徑、source store 被改寫的路徑、recovered content 逃出 blockquote/inert 邊界的路徑、path/symlink escape、SQLite 直連 live 資料庫、installer 覆寫非 owned 檔案（未 force）的路徑。

---

## Important（應儘快修）

### I-1. Installer journal/manifest 完全沒有 fsync，弱於 PRD §7.3 的規範性要求
- 位置：`src/portable_resume/install/transaction.py` — `_write_journal()`（L371-377）、`execute_install()` commit 迴圈與 manifest 寫入（L336-358）。
- PRD `.omx/plans/prd-portable-resume-skills.md` §7.3 明文要求「write and **fsync** a durable journal … replace owned paths one at a time with **directory fsync**」。實作中 journal 用 `Path.write_text` + `os.replace`（無 file/dir fsync）、staged 檔案用 `Path.write_bytes`（無 fsync）、**manifest（commit marker）直接 `write_text` 覆寫，既非 atomic replace 也無 fsync**。
- 後果：process crash 情境（測試有覆蓋）可偵測、可恢復——這部分成立；但 power-loss 情境下 journal 可能整份消失或 manifest 半截，「durable journal 讓 mixed state 可偵測」這個 AC-12 的宣稱在 power-loss 下不成立。PRD 已誠實不宣稱 power-loss 原子性，但「journal 是 durable 的」本身是規範性要求，目前未達。
- 建議：journal 與 manifest 一律 temp + fsync(file) + `os.replace` + fsync(parent dir)；staged 檔在 commit 前 fsync。對照組：`snapshot.py` 的私有 SQLite 副本反而有做 `os.fsync`（L344），核心層紀律比 installer 好。

### I-2. `recover_root()` 對未完成 journal 的語意與 PRD／自身註解都不符：無條件刪 journal、不做完成/失敗封閉
- 位置：`transaction.py` L410-447。
- PRD §7.3：「the next `recover`/mutating invocation **idempotently completes or restores** each recorded path … **unrecoverable drift fails closed** for operator review」。程式碼 L423 的註解也寫「keep journal if unrecoverable drift remains」。
- 實際行為：incomplete journal 只還原 sandboxed backups，**不會**用 journal 記錄的 staged hash 完成或校驗已 committed 的路徑，然後 **無條件 `os.remove(path)` 刪除 journal**（L446）。若 crash 發生在部分 commit 之後（無 backups 的常見情況），recover 回報 `restored_paths: 0`、清掉 journal，root 解除 `E_RECOVERY_REQUIRED` 封鎖，但磁碟上留著新舊混合的檔案，只剩事後 `verify` 才會以 `E_VERIFY_MISMATCH` 發現。
- 後果：`E_RECOVERY_REQUIRED` 的「mutation 封鎖直到狀態乾淨」保證被弱化成「封鎖直到有人跑過一次 recover」，與註解、PRD、以及 `independent-review-deferred.md` 引用的行為描述皆不一致。
- 建議：recover 時逐路徑比對 journal 記錄的 sha256——已 committed 且 hash 相符者視為完成；不符且無 backup 者保留 journal 並回報 fail-closed（或明確標記 requires-operator）；只有全部路徑收斂才刪 journal。

### I-3. Reinstall 會無備份、無警告地覆寫使用者已修改的 owned 檔案（實機驗證重現）
- 位置：`transaction.py` `plan_install()` L198-202（`owned_shared = existing is not None and rel in existing.files` → 直接列入 `replaces`）、`_classify_dest()` L264-266。
- 實測：install claude → 對 `resume-grok/SKILL.md` 追加一行本地修改 → 再次 install（未加 `--force-with-backup`）→ exit 0，修改**直接消失**，`backups/` 目錄不存在，plan 顯示 `replaces: ['resume-grok/SKILL.md'], backups: []`。
- 不一致點：同一種 drift，`uninstall` 會以 `retained_drift` 保留、`verify` 會 fail-closed（實測 exit 7），唯獨 reinstall 靜默銷毀。專案自己的核心倫理是「refusal by default、force 才 backup」；owned-but-drifted 檔案承載的是使用者的工作成果，應至少比照 force 路徑自動備份。
- 建議：`plan_install`/`_classify_dest` 將「owned 但磁碟 hash ≠ manifest 記錄 hash」歸類為 replace+backup（自動寫入 `.portable-resume/backups/`），並在結果 JSON 中明示。附帶一提：`plan_install` 的 `owned` 變數被 `owned_shared` 完全吸收，是死碼，正好是這個判斷該精細化的位置。

---

## Minor / nits

1. **Uninstall 殘留空目錄（實機驗證重現）**：乾淨 install→uninstall 後留下 11 個目錄（六個空的 `resume-*`、`.portable-resume/runtime/portable_resume/resources` 鏈）與 `install.lock`。根因是 `_cleanup_empty_dirs()`（transaction.py L546-554）bottom-up walk 中父目錄的 `dirnames` 是走訪當下快照，子目錄剛被 rmdir 後父目錄仍以為非空而跳過。修法：`try: os.rmdir(dirpath) except OSError: pass` 不做前置判斷，或以 `os.listdir` 重查。空 `resume-*` 目錄可能讓部分 host 列出無 SKILL.md 的殘影。
2. **`codex.py` 用 `getattr(subprocess, "Popen")` 繞過自家靜態掃描**：`tests/security/test_isolation.py::test_runtime_has_no_network_or_source_process_calls` 逐字串斷言 `subprocess.Popen(` 不存在於 src，而 codex zstd decoder（audited、允許的例外）刻意用 getattr 規避。語意上仍成立（zstd 不是 source CLI），但這個靜態閘門對「未來有人如法炮製」零防護，屬 test-theater 邊緣。建議改為顯式 allowlist（掃描全部 call site，僅豁免 `codex.py` 該行並註明 audit 依據）。
3. **request-file 模式的「fixed argv」是 prompt-enforced，非 machine-enforced**：`reader._resolve_invocation()` 在 `--request-file` 模式拒絕 source/action/ref/cwd，但仍接受 `--source-root`（會生效）、`--format json`（會改變輸出形態）、`--within-min`（被靜默忽略）。e2e 測試本身就靠 `--source-root` 注入 fixture，可見是刻意保留的測試縫。風險有限（輸出仍為 inert/sanitized），但被 prompt-injection 說服的 host model 可加旗標偏離「installed wrapper 一律 handoff」的合約。建議：request-file 模式下拒絕 `--within-min`；`--source-root`/`--format` 若要保留測試用途，至少在 SKILL.md 之外的文件記錄此縫隙。
4. **`--host all` 中途 conflict 會丟棄已完成結果的輸出**：`install/cli.py` 迴圈中任一 host 拋 `E_INSTALL_CONFLICT`（如 project scope 下 codex 與 antigravity 共用 `.agents/skills`）即整體以 diagnostic 結束，先前已成功 commit 的 host 安裝了卻沒有任何成功輸出。建議逐 host 收集 per-host 結果（成功與失敗並列）再輸出。
5. **Attestation 文件範圍不一致**：`docs/clean-room-attestation.md` 明寫「intentionally limited to **G001**」，而 `docs/provenance.md` 的 attestation 段落涵蓋 **G001–G004**。兩者應同步（把 attestation manifest 擴到 G004，或在 provenance.md 註明依據）。
6. **`render_session()` 在接近 8 MiB 的合法 session 上 fail-closed（exit 7）**：`--format json` 會成功、預設 handoff 因加上引用前綴/骨架超過 `normalized_content_bytes` 而失敗。fail-closed 方向正確，但屬「同一 envelope 兩種格式一成一敗」的可觀察不對稱，值得在 docs/limitations 記一筆或預留 render overhead 餘裕。
7. **`.omc/` 未列入 `.gitignore`**（`.omx/` 有列）：dual-review 產物與 orchestrator 腳本目前會被視為可 commit 內容。首次 commit 前建議補上。
8. Nits：`cli.py` recover 的 `as_json=bool(ns.json) or True` 恆真；`execute_install` 的 generation 檢查中 `existing.generation != 0` 分支實務上不可達（generation 從 1 起算）；`RootLock` 在 Windows 是 no-op（V1 不 live 支援 Windows、已文件化，僅提醒勿在 Windows 宣稱並發安全）；`_ANSI` regex 未涵蓋非 CSI/OSC 的單字元 escape（如 `\x1bc`），但後續 C0 過濾會移除 `\x1b` 本身，實際不可利用。

---

## 指令驗證結果（實際執行，未跳過）

Brief 指定指令（於 repo root、Python 3.14）：

| 指令 | 結果 |
|---|---|
| `python3 -m compileall -q src scripts tests` | **exit 0** |
| `PYTHONPATH=src python3 -m unittest discover -s tests -q` | **exit 0 — `Ran 145 tests … OK`**（3.29s） |
| `PYTHONPATH=src python3 scripts/portable-resume --help` | **exit 0**；usage 列出正好六個 source key（`antigravity,claude,codex,cursor,grok,opencode`）與 `list|show` |
| `PYTHONPATH=src python3 scripts/portable-resume self-check --json` | **exit 0**；`"ok":true`、六 adapter 全 `ok:true`、`"matrix":{"cell_count":36,"expected":36,"ok":true}` |
| `PYTHONPATH=src python3 scripts/install-resume-skills matrix --json` | **exit 0**；`cell_count:36`、`packaging_cells_supported:36`、**`live_cells_supported:0`、每格 `live_evidence:"not-run"`** |

追加的對抗性實機驗證（temp HOME/project，不觸碰真實 store）：

| 驗證 | 結果 |
|---|---|
| `install --host all --scope global --dry-run`（空 temp HOME） | exit 0；6 結果全 `ok+dry_run`；**HOME 內 0 個檔案被建立**（dry-run 純度成立） |
| install → verify（claude project） | 均 exit 0 |
| 對 owned SKILL.md 注入 drift 後 verify | **exit 7、`E_VERIFY_MISMATCH`**（fail-closed 成立） |
| installed `run_reader.py` + request-v1 + fixture root，並注入 `--expected-source codex` 惡意覆寫 | exit 0；輸出為含 SECURITY BOUNDARY banner 的 handoff；wrapper 正確剝除覆寫、hard-bind 回 claude（e2e 測試亦覆蓋同場景） |
| drifted-owned 檔案 reinstall（無 force） | **exit 0 但本地修改被無備份覆寫**（→ Important I-3） |
| 乾淨 uninstall 後盤點 | 42 檔案移除、0 drift；**殘留 11 個空目錄 + install.lock**（→ Minor 1） |
| 全部測試+上述操作後 `git status --porcelain tests/fixtures` | 僅 `?? tests/fixtures/`（untracked 整目錄，無任何內容變動）——fixture bytes/mtimes 未被任何路徑改動 |

---

## 各維度審查摘要

1. **安全不變量** — ✅ 穩固。全 runtime 僅 `codex.py` 有一個 subprocess call site（audited zstd decoder：固定絕對路徑 allowlist、拒 symlink/world-writable、`env={"PATH":""}`、no shell、5s timeout、16 MiB 輸出上限）；`sqlite3.connect` 只存在於 `snapshot.py` 的私有副本（`mode=ro&cache=private`、`uri=True`、`PRAGMA query_only` 回讀斷言、連線前 realpath commonpath 防逃逸）。hot rollback journal 實測與測試皆 `E_SQLITE_HOT_JOURNAL` fail-closed；`-shm` monitored-not-copied 有專測。`paths.require_regular_no_symlinks` 逐 component `lstat` 拒 symlink，`snapshot._open_no_follow` 走 descriptor-relative `O_NOFOLLOW` + dir_fd，三讀一致 + parent membership 指紋抓 same-stat spoof（`test_verifier_regressions` 有專門的 mtime-spoof 對抗測試）。recovered content 全鏈 inert：sanitize（ANSI/C0/C1/bidi/zero-width 移除、秘密 redaction、binary 剔除）→ contracts 閉鍵驗證（輸出前驗證，失敗時 stdout 為空、exit 8）→ handoff 逐行 blockquote（hostile metadata 換行/OSC-8/RTL-override 注入皆有測試證明無法產生未引用行）。
2. **合約正確性** — ✅。exit code 0/2/3/4/5/6/7/8 對映與 PRD 一致；`--json` 互斥、show 預設 handoff、list 預設 table 皆實作且有測；diagnostics 訊息固定由 code 查表（adapter 文字不可能洩入）、family 名稱僅 basename 化 token；candidates 閉合 schema + 排序在 `validate_envelope` 強制；8 MiB aggregate byte 預算在 runtime validator 與 `tests/helpers/json_schema.py` 參考實作雙軌驗證（`test_contract_equivalence` 共用 accept/reject corpus）。`generated_at` 為唯一非決定性欄位、handoff 無時鐘（`test_u029` byte-identical 專測）。
3. **六個 adapters** — ✅。fixture 計數：claude 7、codex 12、cursor 8、opencode 7、antigravity 6、grok 6，每源皆含 unsupported/corrupt/busy(concurrent-write)/immutability/injection 案例，`fixture.json` manifest 由 `fixture_manifest.py` 強制 `synthetic:true` 與 provenance anchor。結構化簽章 probe（SQLite 欄位表精確比對、JSONL 記錄型別閉集）；未知 schema 一律 `E_UNSUPPORTED_FORMAT` 不猜。Grok adapter 對 `rewind_marker`/`compaction_checkpoint` 這類 timeline-essential 事件 fail-closed 而非跳過，是正確的保守選擇。Claude lineage 重建（fork 擇一、compaction 截斷、broken chain 警告）與 slug-collision 用 recorded cwd 判定皆有專測。
4. **Packaging 6×6** — ✅。`matrix_report` 36 格、frontmatter 僅 `["name","description"]`（render 與 verify_root 雙處強制）；`run_reader.py.tmpl` hard-bind source 並剝除 `--expected-source` 覆寫（e2e 以 subprocess 實跑 installed runner 證明）；codex/antigravity 共 root 衝突誠實回 `E_INSTALL_CONFLICT`（integration 專測 + `docs/host-support.md` 說明）。`supported` 欄位僅是 `packaging_supported` 的相容別名，`live_supported:false` 並列，無混淆。
5. **Installer** — ⚠️ 大致成立但見 I-1/I-2/I-3 與 Minor 1/4。dry-run 純度、root lock（flock + bounded wait）、claim/reference manifest、非 owned 拒絕、force-with-backup、pending journal 封鎖 mutation、journal path escape 防護（`../` 與 root 外 backup 被忽略）皆有實測或測試證據。
6. **Evidence honesty** — ✅ 出色。matrix/self-check/docs/README/prd-verification 全鏈一致：live 全 `not-run`、AC-18 僅宣稱本機 OS、AC-10 明標「pass (filesystem)」、independent review 明文 deferred 且拒絕發明 APPROVE/CLEAR 措辭。`test_provenance_policy` 與 `test_platform_release_gate` 把「不得宣稱 verified-live / 雙 OS」寫成會咬人的測試。本報告即是該 deferred independent review 的其中一席。
7. **Clean-room** — ✅（attestation-based）。src 全樹無 `~/.grok/bundled` 參照（有自動掃描測試）；NOTICE/LICENSE（Apache-2.0）/provenance/attestation 齊備；fixtures 全部帶 `synthetic:true` 且掃描拒絕 `/Users/<name>/` 與 `sk-live-` 樣式。注意：「作者未曾開啟禁止路徑」本質上只能靠 attestation，自動掃描僅覆蓋 shipped tree（列入殘餘風險）。`.omx/tmp/host-probes/` 下有 vendor 文件與 codex system skills 的副本作為規劃證據——`.omx/` 已被 gitignore、不隨 repo 散布，且不含 `~/.grok/bundled/skills/**`；維持不 commit 即可。
8. **測試品質** — ✅ 高。無 skip/only/stub；security 測試以 PATH-shim、subprocess/socket monkeypatch、same-stat spoof、hostile metadata、shell-metachar request 等真實對抗手段驅動 **shipped** 入口（`reader.run`、`scripts/*` subprocess、installed runner、relocated bundle）；e2e 卸除 PYTHONPATH 證明 installed runtime 自行解析。唯一保留意見是 Minor 2 的字串掃描閘門。

---

## Residual risks / 誠實不宣稱

1. **36 格全部是 `verified-filesystem`，0 格 live**：六個 host 的 installed-version 探索、自然語言 activation、request-file 建立、fixed argv 呼叫、deterministic handoff smoke 一項都還沒跑。AC-10 的「36/36 supported installed-version-proven」**尚未達成**，V1 release 依 PRD 仍被此項阻擋——現有文件已正確如此陳述，本報告確認該陳述屬實。
2. **AC-18 dual-OS**：僅 macOS（本機 Darwin 25.4.0 / Python 3.14）有綠色證據；Linux clean-runner 誠實未宣稱。引用 AC-18 的 release claim 需補 Linux runner 產物。
3. **Grok 前綴優先權（AC-13）**：catalog 只落實「owned root + 目標路徑碰撞拒絕」；bundled-skill 優先權的 live 證明未跑，與文件陳述一致。
4. **Clean-room 為 attestation-based**：自動化只能證明 shipped tree 無禁止參照與非 synthetic fixture，無法機器證明過程未接觸 `~/.grok/bundled/skills/**`；attestation 文件範圍尚有 Minor 5 的 G001 vs G001–G004 不一致待補。
5. **秘密 redaction 是 best-effort**（AKIA/gh 系/sk-/Bearer/key=value 樣式），非完整 DLP——README 已誠實聲明。
6. **Power-loss durability**：在 I-1 修復前，installer 的 crash-journal 可偵測性只對 process-crash 成立，不對斷電成立。
7. 本審查為單人（單模型）seat；dual-review 的另一席（Codex）結論應與本報告交叉比對後再合併裁決。

---

*報告完。Verdict: APPROVE WITH MINOR FIXES — deterministic V1 bar 誠實達成；I-1/I-2/I-3 應在正式 release claim 前修復；live 36-cell 與 Linux runner 證據仍是 release 的既知硬閘門。*
