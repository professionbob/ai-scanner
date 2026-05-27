from pathlib import Path
import re
import shutil
from datetime import datetime

MAIN_FILE = Path("main.py")

if not MAIN_FILE.exists():
    raise FileNotFoundError("找不到 main.py，請把這個檔案放在 main.py 同一個資料夾再執行。")

text = MAIN_FILE.read_text(encoding="utf-8")

backup = MAIN_FILE.with_name(f"main_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py")
shutil.copy2(MAIN_FILE, backup)

# =========================================================
# 1) 強化 get_us_market：S&P500 抓不到也有完整美股保底池
# =========================================================

new_get_us_market = '''
def get_us_market():
    # 美股股票池：
    # 1. 優先抓 S&P 500
    # 2. 加入 AI / 光通訊 / 國防 / 金融科技 / 電力主題成長股
    # 3. 如果 Wikipedia 抓不到，直接用 fallback，避免美股池為空

    fallback = [
        # Mega cap / AI
        "NVDA", "AVGO", "AMD", "MU", "MRVL", "ARM", "SMCI",
        "MSFT", "GOOGL", "AMZN", "META", "AAPL", "TSLA", "ORCL",

        # AI Infra / Data Center / Neocloud
        "CRWV", "NBIS", "APLD", "IREN", "CORZ", "CLS", "DELL", "HPE",

        # Optical / CPO / Semiconductor equipment
        "AAOI", "LITE", "COHR", "FN", "AXTI", "AEHR", "ONTO", "MKSI",

        # Robotics / Automation
        "SERV", "SYM", "TER", "ISRG",

        # Defense / Drone / Space
        "KTOS", "AVAV", "ONDS", "ASTS", "LUNR", "RKLB",

        # Fintech / Crypto beta
        "SOFI", "HOOD", "COIN", "MSTR",

        # Nuclear / Power
        "OKLO", "SMR", "CEG", "VST", "GEV",

        # ETF / Benchmark
        "QQQ", "SOXX", "SPY"
    ]

    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        sp500_df = tables[0]

        sp500 = (
            sp500_df["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .tolist()
        )

        all_tickers = sp500 + fallback
        result = list(dict.fromkeys(all_tickers))

        if not result:
            print("get_us_market：S&P500 結果為空，改用 fallback")
            return fallback

        return result

    except Exception as e:
        print("get_us_market 錯誤，改用保底美股池：", e)
        return fallback
'''

pattern_get_us = r'def get_us_market\(\):[\s\S]*?(?=\ndef get_tw_market\(\):)'
if not re.search(pattern_get_us, text):
    raise RuntimeError("找不到 get_us_market()，請確認 main.py 裡有 def get_us_market():")

text = re.sub(pattern_get_us, new_get_us_market + "\n", text, count=1)


# =========================================================
# 2) 加入股票池載入完成通知
# =========================================================

load_notify = '''send_telegram_once(
    f"股票池載入完成\\n"
    f"美股：{len(US_MARKET)} 檔\\n"
    f"台股：{len(TW_MARKET)} 檔"
)
'''

if "股票池載入完成" not in text:
    pattern_market_load = r'(US_MARKET\s*=\s*get_us_market\(\)\s*\nTW_MARKET\s*=\s*get_tw_market\(\)\s*)'
    if re.search(pattern_market_load, text):
        text = re.sub(
            pattern_market_load,
            r'\1\n' + load_notify + '\n',
            text,
            count=1
        )
    else:
        print("提醒：找不到 US_MARKET = get_us_market() / TW_MARKET = get_tw_market()，略過股票池載入通知插入。")


# =========================================================
# 3) 修美股 batch 空轉問題 + 加入美股掃描啟動通知
# =========================================================

old_batch_block = '''if market_type == "TW":
            batch = TW_MARKET
        else:
            start = scan_pointer
            end = start + MAX_SCAN_PER_ROUND

            batch = market_universe[start:end]

            scan_pointer = end

            if scan_pointer >= len(market_universe):
                scan_pointer = 0'''

new_batch_block = '''if market_type == "TW":
            batch = TW_MARKET
        else:
            start = scan_pointer
            end = start + MAX_SCAN_PER_ROUND

            batch = market_universe[start:end]

            # 防止 scan_pointer 跑到尾端後 batch 變空，造成美股沒有選股
            if not batch:
                scan_pointer = 0
                start = 0
                end = MAX_SCAN_PER_ROUND
                batch = market_universe[start:end]

            scan_pointer = end

            if scan_pointer >= len(market_universe):
                scan_pointer = 0

            # 美股開盤時，每 30 分鐘回報一次掃描狀態，確認不是沒進入美股掃描
            if mark_once_interval("US_scan_start", 30):
                send_telegram_once(
                    f"美股掃描啟動\\n"
                    f"美股池：{len(market_universe)} 檔\\n"
                    f"本輪掃描：{len(batch)} 檔\\n"
                    f"範圍：{start} ~ {end}"
                )'''

if old_batch_block in text:
    text = text.replace(old_batch_block, new_batch_block, 1)
else:
    print("提醒：找不到標準 batch 區塊，改用較寬鬆 regex 嘗試替換。")
    pattern_batch = r'''if market_type == "TW":\s*
\s*batch = TW_MARKET\s*
\s*else:\s*
\s*start = scan_pointer\s*
\s*end = start \+ MAX_SCAN_PER_ROUND\s*
\s*batch = market_universe\[start:end\]\s*
\s*scan_pointer = end\s*
\s*if scan_pointer >= len\(market_universe\):\s*
\s*scan_pointer = 0'''
    if re.search(pattern_batch, text):
        text = re.sub(pattern_batch, new_batch_block, text, count=1)
    else:
        print("警告：batch 區塊沒有自動替換成功。你可能需要手動替換主迴圈那段。")


# =========================================================
# 4) 放寬美股正式訊號：避免掃了但完全不發
# =========================================================

text = text.replace("S_SMART_MONEY_MIN = 6", "S_SMART_MONEY_MIN = 4")
text = text.replace("A_SMART_MONEY_MIN = 3", "A_SMART_MONEY_MIN = 2")
text = text.replace("MIN_SMART_MONEY_FOR_SIGNAL = 3", "MIN_SMART_MONEY_FOR_SIGNAL = 2")


MAIN_FILE.write_text(text, encoding="utf-8")

print("✅ main.py 已完成修補")
print(f"✅ 備份檔：{backup.name}")
print("✅ 請重新部署 / restart Railway 或你的執行環境")
print("✅ 美股開盤後 Telegram 應該會先收到：美股掃描啟動")
