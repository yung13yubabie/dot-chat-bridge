# DOT bridge：Codex 接手交接

更新：2026-10-24。此交接分支只保存去識別化文件，不新增橋接功能或真實派工。
**請先讀本檔。完整 bridge 尚未驗收；禁止以歷史 fixture、面板或 Chat UI 回讀冒充 Work 成功。**

## 目前可確認的真實驗證矩陣

| 層次 | DOT→Chat | DOT→Work |
|---|---|---|
| 正式工具路徑 | 既有對話：`mcp__codex_app__send_message_to_thread` | 新 Work 雲端任務：`mcp__codex_app__create_thread`，`target.type=chatgptWorkCloud`；須明確授權新任務 |
| 已發生派工 | 一次新合成訊息確實送出，native 回條確認目標；未重送 | 舊建立呼叫確實留下回條，但只有暫存 `clientThreadId`，沒有正式 `threadId`；本輪沒有新建或重送 |
| 接收端內容 | 精確新 prompt 與 completed 回合已由 native reader 核對 | 本輪真實 `read_thread` 取得完整舊 prompt、completed/error-free 回合與正式 user／assistant ID |
| 目標獨立執行 | 新測試未提供期望輸出；UI 看到的完整結果與事先保存的 oracle／父端獨立核對一致，限定範圍通過 | 舊 prompt 已含期望答案；只能證明回覆符合協定，獨立執行 **未證實** |
| 完整 assistant 結果回讀 | 指定瀏覽器操作者已讀到完整 JSON，父端讀其報告後轉交；此為半自動 UI pull-return | **真實 native 全文 pull retrieval 已確認**，不是 preview、reference 或本地算出的答案；本輪讀回的舊結果與原 task／nonce／方向一致 |
| 正式訊息身分 | native reader 與父端精確 global anchor 已確認 assistant UUID；UI 本身未顯示 UUID | native reader 提供正式回合與訊息 ID；但不能據此補造原建立操作的暫存→正式 ID 映射 |
| 工具正文能力 | native 仍只有 content reference；父端精確 global read 是空正文、omitted=true、無截斷／cursor；不要重讀相同接口 | 舊 Work-correlated 回覆正文可讀；**不要把 Chat 的正文阻礙泛化到 Work** |
| Provider binding／實際模式 | 目標對話綁定已知；實際 host mode 未獨立 attested | 原建立操作的正式 ready／ID 映射與實際 Work 模式 **未證實**；`kind=chatgpt` 及回覆自稱 Work 都不能代替模式證據 |
| 實際模型 | 沿用既有對話；實際模型 unknown | 沿用任務預設；實際模型 unknown；未使用逐次選模 |
| DOT sink ACK／callback | **未接線、未驗收** | **未接線、未驗收** |
| 原部署或候選 DB 入庫 | 本次真實測試未入庫 | 舊回覆未回填任何 DB；本輪沒有入庫 |
| 完整 bridge 驗收 | 未通過 | 未通過；strict checker 仍為 `pending_thread_resolution` |

Chat 詳細證據界線見 [LIVE_ACCEPTANCE.md](LIVE_ACCEPTANCE.md)；人工協作步驟見
[SEMI_AUTOMATIC_UI_PULL.md](SEMI_AUTOMATIC_UI_PULL.md)。UI 操作者報告與原生正文回條是不同來源。

## 插件／面板與真實通道是不同層

主線本輪報告的私人測試插件 health：版本 `0.1.0-probe`，authenticated tool call 與 durable
store configured 為 true；UI forwarding、Chat dispatch、Work dispatch 皆 unverified，events
disabled，Chat／Work acceptance 皆 unmet。本輪本機未再呼叫 health；這裡標為父端回報。

這只能支持插件可被認證讀取及其能力聲明，不能證明真派工、執行或 ACK。面板開啟／queued
同樣不是成功。固定 probe 工具只接受自己建立的固定合成任務與有效 claim／nonce，沒有已暴露的
任意 DOT sink、callback destination 或 ACK 訂閱。候選 Store 的本機 pending outbox 也不是傳送。

## 本輪實際做了甚麼

- 讀取原 Work 建立回條、舊結果與既有交接，先確認任務已存在，沒有再派。
- 使用正式 `read_thread` 唯讀查詢一次既有 Work-correlated 對話：全文、精確 prompt 與 completed
  同回合相符。沒有讀取 Chat 來充當 Work 進度，沒有從摘要補正文，沒有計算答案冒充遠端結果。
- 查閱目前 `create_thread`／`read_thread`／`list_threads` 工具 schema。`list_threads` 首次
  limit=100 被參數驗證擋下；一次修正為 50 後完成。匹配列仍只有 `kind=chatgpt`，未提供 ID 映射或模式。
- 以原始未改動的 Work dispatch 與這次真實 read 執行既有 `receipt_check.py`：exit 2，
  `accepted=false`、`pending_thread_resolution`。這是預期未通過，不能標成端到端 PASS。
- 執行既有 `correlated_result.py`：exit 2，`status=correlated_payload_verified`；
  `payload_verified` 與 `tool_pull_return_verified` 為 true。Provider mapping、獨立執行、模式、
  模型及 callback 保持未證實。
- 比對隔離副本與保存基線的 55 個受追蹤檔案，bytes 相同；原工作樹 clean。獨立審查者亦確認
  完整實際正文與兩份 SHA，未見本範圍內必修的程式缺陷。
- Git clone 的本機 MSYS helper 遇到系統錯誤。未擴權或重試該 helper；改由已保存且 SHA 核對的
  合法 bundle，以原生 Git init／unbundle／checkout 還原。這不是重試被拒的原始 archive。
- **程式修改：無。新 fixture／mock adapter：無。新真實測試：未執行。** 本輪只修正文檔範圍，
  明確區分 Work 全文已讀回與 Chat 工具正文仍受阻。
- 265 個方法是先前程式保存點的結果（90 preserved／92 candidate／83 independent）；本輪
  **沒有重跑**單元套件，也沒有執行既有 Work guard 單項測試。文件保存執行 manifest／diff 檢查。

## 已確認缺口與未知原因

1. **Work 正式 ready／ID 映射缺失。** 原回條只有 client ID；目前工具未暴露可據此取得正式 ID 的
   resolver。完整 prompt／nonce 關聯是真實內容證據，不能改寫成平台 mapping。舊建立動作不可重送。
2. **Work 實際模式與獨立執行未證實。** 工具請求選 Work，不等於收到明確 host-mode metadata；
   舊 prompt 已給答案。這兩項都無法靠本地 parser 修好，不能放寬 gates。
3. **現有 transport 是 Chat-only。** `candidate_protocol/transport.py` 明確阻擋 Work；
   `test_transport.py` 已有該 guard。這是刻意未接線，非本輪可用真實接口修復的小 bug。
   不可只刪掉 target 檢查就稱為 Work adapter；Work 的建立／暫存／正式綁定與不確定結果需真實契約。
4. **Chat 完整正文 API 能力缺口。** 已知現象是 reference／omitted；平台為何未暴露正文仍未知。
   不是已證實的授權拒絕，不應猜 endpoint、讀內部 DB 或提取瀏覽器 token。
5. **DOT sink 與 ACK 契約缺失。** 需要真實授權目的地、來源／task／nonce 綁定、attempt／ACK ID、
   可獨立讀回的接收紀錄及重複回覆行為。callback 未實作；outbox 與人工核對紀錄都不能冒充 server ACK。
6. 原 bridge 可讀原始碼、原 36 DB／12 panel 測試仍缺。保存的來源 commit／archive hash 是 metadata，
   新候選並不是找回原版。此交接沒有解決原部署相容性。

## Codex 接手順序

1. 先核對分支與 `git status --short`，讀 `.ai/spec-kit.md`、CURRENT_STATE、TASKS、DECISIONS、
   HANDOFF，以及本檔。任何未提交修改先保存，不覆寫別人的成果。
2. 先做檔案完整性核對；不要為取得綠燈而改寫舊 baseline manifest。

   ```powershell
   python -B tools/verify_candidate.py
   ```

3. 讀程式入口：`native-bridge-probe/receipt_check.py`（strict gate）、`correlated_result.py`
   （有限歷史內容關聯）、`candidate_protocol/store.py`（本機 lifecycle／outbox）、`transport.py`
   （Chat-only 注入邊界）。再讀 `candidate_protocol/TRANSPORT.md`、`docs/INTEGRATION_EVIDENCE_REQUIRED.md`
   與 `docs/REBUILD_GATES.md`。保存過的原始私有回條不在 Git，勿從合成 fixtures 推斷真實路由。
4. Work 下一個最小支援需求是：**取得既有建立操作的受支援 ready／client-to-formal mapping 與
   Work 模式來源證據**。目前沒有已知 callable resolver；若平台未提供，保持 BLOCKED 並報告，
   不再查同一完整回覆、不重建舊任務、不擴權或發明 API。
5. 後續若使用者另外明確要求一個全新 Work 雲端驗收，才在執行前保存新 task／nonce 與一次性 ledger，
   透過 `create_thread` 的 `chatgptWorkCloud` 目標建立一次，省略 model／thinking。
   這份交接**不授權現在執行**。若回條仍只有 client ID，立即保留不確定／待解析狀態，不重建。
   不把 client ID 傳給需要 threadId 的工具。僅正式 ID 可供 `read_thread` 使用；已觀測可接受的
   request 為 turnLimit=1、includeOutputs=true、maxOutputCharsPerItem=20000。
6. 真實驗收必須保存未先給答案的 prompt、真實派送回條、正式接收身分、completed 同回合完整 assistant
   正文、正確 task／nonce／方向與獨立比較結果。模式／模型仍無 metadata 時標 unknown；不得以
   `receiver=Work` 自述提升模式證據。入庫、回傳與 ACK 需另外以實際契約驗證。
7. 若修改程式，先重現具體失敗，再做最小修正並執行相關測試。完整離線回歸與既有 Work guard 指令：

   ```powershell
   python -B tools/run_offline_suites.py
   python -B -m unittest candidate_protocol.tests.test_transport.TransportIntegrationTests.test_work_is_explicitly_unwired_in_this_chat_adapter
   ```

   這些只驗證本地行為。通過條件包括拒絕 stale nonce／錯來源／暫存 ID／省略或不完整正文，
   不明送出不重送，重複 ingest 不新增結果／事件；不能據此宣稱遠端 exactly-once 或 callback。

## 不可改動與停止條件

- **已取消的 probe_chat_v1 不得恢復或更動。** 不 claim、cancel、submit 或回填舊結果。
- 既有不確定建立／派送不可重送；先查證結果。相同內容 reader 已確認受阻者不反覆呼叫。
- 不讀被禁止的 session 目錄、不重試被拒 archive、不擷取 cookies／tokens，不新增帳密或持續權限。
- 影視 session 是目前唯一 IAB 操作者；需要 UI 先由主線協調，不爭用，也不用桌面 Computer Use 替代。
- 此次只提交交接文件：不合併 main、不部署、不新派真實任務。交接推送與讀回完成後停下。

## 工作樹、保存範圍與未保存項

交接起點是已保存的 `c8ab30952cc99d8cc48bde293c4ef8e0ef591152`。原候選工作樹與新隔離
副本開始時皆 clean，55 檔比對一致；沒有待搬移的程式 diff。本次新修改只有 README、.ai 狀態、
本交接文件與 manifest。原候選分支及 main 不變，交接另用 `codex-handoff-20261024`。

本地私有證據另外保留：原派工回條、本輪 native read、有限 listing、strict／correlation 輸出、
hash、環境失敗及獨立審查。它們含真實識別碼，**刻意不推送**；不在 repo 不等於遺失。
若接手環境需要原始證據，請使用者提供已授權且可讀的去機密副本，不擴張存取。
原始缺失 source／36／12 測試沒有找回；callback／ACK／Work 模式／獨立執行不會因本次保存而變成通過。

官方產品說明支持可見任務、查看結果與協調的流程；不提供此舊 client ID 的映射證據。
實際 callable schema 以已連線工具為準，勿自行拼 HTTP API。
[Tasks and memory](https://learn.chatgpt.com/docs/dots/tasks-and-memory)、
[Get started with ChatGPT Work](https://learn.chatgpt.com/docs/get-started-with-work)。
