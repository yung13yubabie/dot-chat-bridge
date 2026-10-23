# 單次 canary 驗收規格（封存提案，未執行）

**目前狀態：BLOCKED／未核准／未派送。** 現有正文讀取是 content_omitted；不能以另造測試繞過此阻塞。
以下只摘錄之後正文通路恢復、再取得明確核准時的最小操作。這次文件保存沒有產生任務、nonce 或資料庫。

| 項目 | 限制 |
|---|---|
| 接收 agent | 擁有者已指定的既有合成 Chat 對話。sender=DOT、target=Chat、return_target=DOT；不建立 Work、不轉派其他 agent |
| 目的地識別 | 使用控制端私有證據中的正式對話識別碼作允許清單；真實識別碼不寫入 repo，不猜測或替換目的地 |
| 派送通道 | 一次 mcp__codex_app__send_message_to_thread；只傳 threadId 與 prompt。模型沿用該對話，actual model 無權威來源時維持 unknown |
| 合成資料 | 核准後才產生新的 task ID／nonce。values=[17,41,8,26,53]；要求計算 sum／min／max，回覆一個 JSON 物件 |
| 回覆欄位 | task_id、nonce、receiver=Chat、return_target=DOT，以及 output.sum、output.min、output.max。預期數值不得放入發送提示 |
| 額度上限 | 最多 1 次真實派送、3 次派送後唯讀呼叫（合計原生訊息定位與完整正文讀取）、90 秒停止。使用既有對話正常額度；確切費用／credits 未知 |
| 禁止擴張 | 不自動重送、追問、轉派、改模型、開瀏覽器、讀私人來源、修改固定測試任務、申請憑證／持續權限或部署 |

## 完整結果的取得方式

目前沒有可用方法。先由既有授權的全域對話／訊息讀取通路提出可核對的恢復證據：
完整且非空的最終正文、content_omitted=false、正確正式訊息／對話身分、completed 狀態，且不是 content reference。
這不是要求現在重試同一內容；通路未恢復時派送次數必須為零。

通路恢復且另行核准後，保存派送前 baseline turn IDs，再派送一次。以原生讀回定位新回合的正式訊息識別碼，
再以已證實可用的完整正文讀取通路取得該最終回覆。保留來源工具的可核對證據於私有控制端，不上傳原始回條。
只有回覆欄位自稱正確、摘要、手動複製或預期答案不能取代此步。

## 驗收終點與停止條件

1. DOT 保存實際派送回條及新的同回合收件證據，排除 baseline 中的舊回合。
2. DOT 取得可追溯的完整最終正文，精確核對 task／nonce／方向／正式身分與 completed 狀態。
3. 控制端獨立計算預期輸出，只用於比對實際回傳內容，不得拿預期值冒充接收端結果。
4. 若同一次核准另包含本機入庫，將已驗證的真實回傳放入全新合成候選資料庫，再提交同一回條一次：
   必須只有一筆結果、一筆事件、相同 event ID，第二次回覆為 duplicate。
5. 此終點只涵蓋原生 pull-return 與「新本機候選」入庫。原部署資料庫、push callback、真實模型／mode、
   原 lifecycle 相容性及跨系統 exactly-once 仍分別標示 BLOCKED／NOT RUN，不能合併宣稱完整 bridge 成功。

正文省略、身分／nonce 不符、queued、逾時或不確定結果都不能標成功。保留已知識別資料並核對現況；
不自動重送或取消其他任務。到達呼叫／時間上限即停止，標示 INCONCLUSIVE 或 BLOCKED。
要驗收原部署，另需可讀原碼與不影響舊固定任務的新隔離 namespace；本提案不授權該變更。
