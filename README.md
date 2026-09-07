# AI 股票掃描器

這個掃描器適合用 GitHub Actions 以一次性工作執行：每次啟動只掃描當下開盤的市場，完成後即正常結束，不需要常駐主機。

## GitHub Actions 設定

1. Fork 或 push 專案到 GitHub（公開儲存庫可使用 GitHub-hosted runner 的免費額度；實際額度依 GitHub 方案為準）。
2. 到 **Settings → Secrets and variables → Actions** 新增 Repository secrets：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 啟用 Actions。`.github/workflows/scheduled-scan.yml` 會在週一至週五每 15 分鐘觸發，也可以從 Actions 頁面手動執行。

Telegram 憑證只由 Secrets 注入環境變數，不應提交到版本庫。工作流程使用 GitHub Actions cache 保存 `.scanner-state/state.json`，包含掃描游標、通知節流與推薦紀錄，避免每次 runner 啟動都從零開始。工作設有 concurrency 鎖，避免兩次掃描同時覆寫狀態。

> GitHub 的排程使用 UTC，而且可能在尖峰時段延遲；程式仍會判斷台股／美股是否開盤，非開盤時段會直接結束。

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
