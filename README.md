# AI 股票掃描器（第二階段：分批全市場掃描）

這個掃描器適合用 GitHub Actions 以一次性工作執行：每次啟動只掃描當下開盤的市場，完成後即正常結束，不需要常駐主機。

## GitHub Actions 設定

1. Fork 或 push 專案到 GitHub（公開儲存庫可使用 GitHub-hosted runner 的免費額度；實際額度依 GitHub 方案為準）。
2. 到 **Settings → Secrets and variables → Actions** 新增 Repository secrets：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 啟用 Actions。`.github/workflows/scheduled-scan.yml` 會在週一至週五每 15 分鐘觸發，也可以從 Actions 頁面手動執行。

Telegram 憑證只由 Secrets 注入環境變數，不應提交到版本庫。工作流程使用 GitHub Actions cache 保存 `.scanner-state/state.json`，包含掃描游標、通知節流與推薦紀錄，避免每次 runner 啟動都從零開始。工作設有 concurrency 鎖，避免兩次掃描同時覆寫狀態。

> GitHub 的排程使用 UTC，而且可能在尖峰時段延遲；程式仍會判斷台股／美股是否開盤，非開盤時段會直接結束。

## 全市場名單與篩選

- **美股**：免費名單來自 Nasdaq Trader 的 `nasdaqlisted.txt` 與 `otherlisted.txt`，涵蓋 NASDAQ、NYSE 與 NYSE American（AMEX）。程式依交易所、ETF/test/financial-status 欄位、名稱及代號格式排除 ETF、基金、權證、權利、單位、優先股及無效代號，再以 Yahoo Finance 日線留下股價至少 **US$5**、20 日平均成交量至少 **500,000 股**的股票。
- **台股**：免費名單來自 TWSE 與 TPEx 的公司基本資料 OpenAPI；上市公司轉為 `.TW`，上櫃公司轉為 `.TWO`。僅接受四位數普通股公司代號，並以股價至少 **NT$10**、20 日平均成交量至少 **100,000 股**作為流動性條件。
- Nasdaq Trader、TWSE/TPEx 與 Yahoo Finance 都是免費、best-effort 資料，可能延遲、暫時限流、改版或缺漏，並非交易所即時報價。任何一個市場的名單下載或解析失敗時，該市場會完整退回程式原有股票池，不會中止工作流程。

## 分批與游標

每次 Action 的 job 上限為 14 分鐘，掃描器本身預留安裝與狀態保存時間，在 720 秒停止展開新標的。預設每輪從美股池取 20 檔、台股池取 30 檔，並分別保存 `us_scan_cursor` 與 `tw_scan_cursor`；游標只依實際完成且由市場批次選出的股票前進，優先股本身不額外推進游標。若途中超時，下一次對應市場開盤時會從第一個未完成的市場股票接續；到尾端後環繞，逐輪覆蓋全市場。可用 `US_BATCH_SIZE`、`TW_BATCH_SIZE`、`MAX_RUN_SECONDS` 調整，但過大的批次會受到免費來源限流及 Action 時限影響。

每一輪都先加入下列優先股，之後再加入游標批次並去重：

- 美股：`ONDS`、`AAOI`、`AXTI`、`DELL`、`NBIS`、`NVDA`、`AMD`、`AVGO`、`MU`、`TSM`
- 台股：`2330.TW`、`3711.TW`、`2356.TW`

正式掃描依台北與紐約當地時間，只在對應市場的平日正常交易時段執行（美股夏令時間會自動換算）；既有盤前與收盤報告時段及節流邏輯仍保留。交易所臨時休市、個別股票停牌、特殊半日市況或資料商延遲仍可能使整輪或某檔沒有結果，免費版本不保證完整交易日曆。

## 本機執行

```bash
python -m pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py
```

每次 `python main.py` 只執行一輪。若未設定兩個 Telegram 環境變數，程式會立即以錯誤結束，而不會靜默漏送通知。

## 測試

```bash
python -m pytest -q
```
