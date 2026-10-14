# 真正執行抓資料的程式，負責去 TDX 交通資料「我要抓 Station 還是 Availability → 呼叫 API → 存 JSON」

import json # 用來處理 JSON  (剛好要抓的API資料 是JSON)
import logging # 可以讓程式可以產生 log / 執行紀錄
from datetime import datetime, timezone # 用來抓取當前時間
from pathlib import Path # 用來處理 檔案路徑的工具 因為抓API資料後 需要自動建立與處理路徑

import click # 用來建立CLI (命令提示介面) python套件
from dotenv import load_dotenv
from tdx import build_session, get_token # 拿取tdx.py所寫的兩個函式

# 共用常數
BASE = "https://tdx.transportdata.tw/api/basic/v2/Bike" # TDX 資料 API endpoint (可以在公共自行車即時車位 & 租借站位資料 - API服務介接位址中找到)
RAW_DIR = Path("data/raw") # 原始資料的資料夾(變數)，把原始資料儲存並建立路徑至 data/raw

# DATASETS集中管理，把同一類東西的相關資訊，放在同一個地方的設定表 (資料的說明書)
DATASETS = {
    "station":{
        "url": f"{BASE}/Station/City",
        "partition_by_hour": False, # 靜態 / 基本資料資料、不需要按小時分開處理 (False) 主要是我把抓回來的資料，存檔時要不要依照『小時』建立不同的資料夾
        "required": {"StationUID", "StationName", "StationPosition", "BikesCapacity"}, # required為要求station 必須 或 需要最少這 4 欄位。 這搭配後續的missing，若API資料有異動 missing抓到後就會 避免繼續處理錯誤資料
    },
    "availability":{
        "url": f"{BASE}/Availability/City",
        "partition_by_hour": True, # 即時資料 會隨時間變化的狀態資料，故每小時分割
        "required": {"StationUID", "AvailableRentBikes", "AvailableReturnBikes", "ServiceStatus"},
    },
}

# 設定log的格式
logging.basicConfig(
    level = logging.INFO, # level是我要讓 logging 系統顯示到什麼程度的訊息 (有分程度，INFO 以上的重要程度都顯示) 因為如果連DEBUG也顯示，資料會太多並洗版
    format = "%(asctime)s %(levelname)s %(name)s %(message)s" # 每一行 log 要長什麼樣子，參數的寫法是 logging 專用的格式化字串 asctime為時間 levelname為等級 name為記錄器的名稱 message為實際訊息
)
log = logging.getLogger("fetch") # 建立名為 fetch 的日誌記錄器

# 做CLI目的是為了不需要修改 Python 原始碼，就能透過 Terminal 傳入不同的參數，例如資料集或城市，讓同一支程式依照輸入執行不同的功能；同時也方便後續搭配排程工具進行自動化
# 程式整體核心 main，另特定設定三個參數 dataset、 city、 show_keys (抓哪種資料、哪個城市、要不要只看第一筆欄位)
@click.command() # 為了以下main函式 變成一個可以從「命令列（Terminal / CMD）」執行的指令，Click是 Python 套件，做命令列介面（CLI）可接受 Terminal 的參數。
@click.option(
    "--dataset",
    type = click.Choice(list(DATASETS)), # 把DATASETS字典資料變成list，像是["station", "availability"]，告訴click只能選 station 或 availability (click.Choice(...)是「允許使用者選哪些選項」的集合)
    required = True # 輸入--dataset 是必須提供的 因為有兩個 不然程式不知道是抓 station 還是 availability
)
@click.option(
    "--city",
    default = "Taichung", # 如果使用者沒有輸入city，就會預設使用Taichung
    show_default = True # 在 Click 顯示說明（help）時，把預設值也顯示出來 ex.python fetch.py --help，會顯示：--city TEXT  [default: Taichung]
)
@click.option(
    "--show-keys", # --show-keys 是給使用者在 Terminal 輸入的名稱，主要是為了以下if 為了印出 API 第一筆資料 確認TDX API回傳的資料 (像是要當需要檢查 API時 使用的)
    is_flag = True, # 一種開關的意思，如果在Terminal輸入--show-keys 就會是True，若沒有 則為False
    help = "只印出第一筆資料，用來確認欄位名稱" # 執行--help，Click 就會把這段說明顯示給使用者
)

def main(dataset: str, city: str, show_keys: bool) -> None: # 括號中設定的資料型別，是為了跟程式、IDE、其他開發者約定這應該是什麼型別；另外None是為了 不預期回傳一個資料值
    load_dotenv() # 讀.env
    spec = DATASETS[dataset] # DATASETS是上述的設定字典；dataset是click的輸入資料，對應是station 還是 availability
    fetched_at = datetime.now(timezone.utc) #  main() 執行到這一行時，記錄「這次程式抓取資料的時間」 (我在什麼時間取得這批資料)；另外會針對這個時間拿它來決定檔案怎麼命名、放在哪裡；使用UTC+0主要是大部分的程式與軟體都是依照UTC為主
    
    session = build_session() # 這是回到tdx抓函式
    token = get_token(session) # 這是回到tdx抓函式

    url = f"{spec['url']}/{city}" # 從 spec 字典中取出 url 對應的值，並將它與 city 組合成新的網址，存進 url 變數中，形成API網址。
    log.info("GET %s", url) # 嘗試紀錄準備送出的請求url 並留有紀錄(GET 是API 文件要求的方式)；("GET %s", url) = GET + url，%s是佔位符，為了放上url的字串
    resp = session.get( # 發送 HTTP GET 請求 (response)，Python 發送 HTTP GET 請求的基本寫法 (requests 套件)
        url,
        params={"$format": "JSON"}, # params網址查詢參數，期望回傳的資料格式是 JSON
        headers={ # HTTP 標頭，告訴伺服器這次請求的相關資訊
            "authorization": f"Bearer {token}", # 傳送 API 驗證憑證；Bearer：表示使用 Bearer Token 這種憑證傳遞方式
            "accept-encoding": "gzip" # 如果可以，請用 gzip 壓縮格式傳送回應內容 (當資料量較大時，壓縮可以減少傳輸的資料量
        },
        timeout=30, # 設定連線與讀取等待的逾時限制，時間上限為30秒
    )
    resp.raise_for_status() # 檢查 HTTP 狀態碼是否表示請求失敗
    records = resp.json() # 將 HTTP 回應中的 JSON 文字解析成 Python 資料，並存入records

    # 根據 TDX 官方 API 文件，正常的200 OK回應結構最外層是 JSON 陣列，故解析為list，故resp.json() 解析後會得到list，則records必須為list
    if not isinstance(records, list) or not records: # if not isinstance 是 Python 裡常見的條件判斷寫法，意思是：如果某個變數不是指定的資料型態，就執行接下來的程式碼
        raise SystemExit(f"API 回傳格式不符：預期是站點清單（JSON 陣列），實際拿到 {type(records).__name__}：{str(records)[:300]}") # raise SystemExit是Python用來結束程式執行的一種寫法；如果 records 不是列表（list，或者 records 是空的，就顯示錯誤訊息並結束程式；.__name__ 是用來取得資料型態的名稱

    if show_keys: # 回到上述的 show_keys，如果在終端機使用的指令有show_keys = True，就會跑此程式，就把API回傳的第一筆站點資料印出來，顯示固定排版與欄位，並結束此次執行 (不需要處理或儲存資料)。
        click.echo(json.dumps(records[0], ensure_ascii=False, indent=2)) # click.echo() 是 Click 套件提供的輸出功能，作用類似 Python 的 print；ensure_ascii=False 保留中文，不然中文可能會顯示成 Unicode 跳脫形式；indent=2 把每一層資料縮排 2 個空格，讓資料更容易閱讀
        return # return 結束目前的 main() 函式，直接返回呼叫它的地方 (因後面還有missing = spec...)

    missing = spec["required"] - set(records[0].keys()) # 找出spec(字典)中的required欄位，減掉records (API回傳資料) 是否有遺失的欄位；set() 是將這些鍵轉換成集合，就可以很方便地使用 - 找出缺少的欄位；keys()：取得字典的所有鍵 (key & value)
    if missing:
        raise SystemExit(f"缺少欄位 {missing}\n實際欄位：{sorted(records[0])}") # 如果有遺失 就報錯，然後依照sorted 字母順序排序 方便閱讀與檢查

    log.info("取得 %d 筆", len(records)) # 紀錄Log，當API取回幾筆資料並記錄下來 (len是指資料中有多少個元素)

    # 建立資料夾 使用輸出資料夾路徑為名稱(output director)，組合出來的路徑就會類似：data/raw/station/city=Taichung/dt=2026-10-12
    out_dir = RAW_DIR / dataset / f"city={city}" / f"dt={fetched_at:%Y-%m-%d}"
    if spec["partition_by_hour"]: # 因為partition_by_hour有兩種布林值，如果選擇的是availability(partition_by_hour=Ture，則需要多判斷額外增加一層 小時資料夾)，例如：data/raw/availability/city=Taichung/dt=2026-10-12/hour=19/
        out_dir = out_dir / f"hour={fetched_at:%H}" # %H 是 f-string 中的日期時間格式化寫法，%H 為 24 小時制的小時並以兩位數顯示
    out_dir.mkdir(parents=True, exist_ok=True) # 確保資料夾可以正常寫入，mkdir為建立資料夾，parents=True為上層資料不存在時 就一起建立，exist_ok=True為如果資料夾已存在 也不用特別報錯。

    # 檔案名稱、把 API 資料寫入 JSON 檔案，最後記錄寫入結果
    out_path = out_dir / f"{fetched_at:%Y%m%dT%H%M%SZ}.json" # 使用上述建立好的資料夾(out_dir)加入檔案名稱並組合起來；%d為日期 T為日期與時間的分隔符號 %S為秒數 Z表示 UTC 時間，例如：20261012T193045Z.json，最後得到：data/raw/availability/city=Taichung/dt=2026-10-12/hour=19/20261012T193045Z.json
    out_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8") # write_text() 把文字寫進檔案，json.dumps(records) 把資料轉換成 JSON 文字，encoding="utf-8" 決定把文字寫入檔案時，使用什麼編碼方式 (指定使用 UTF-8 文字編碼，將文字寫入檔案)
    log.info(
        "已寫入 %s (%.1f KB)", # .1 小數點後保留 1 位，f 浮點數，KB 顯示的單位文字，例如：數值是 12.3456，使用 %.1f 後會顯示12.3 KB
        out_path, # 同上方的%s 將任何轉換成字串的物件
        out_path.stat().st_size / 1024 # out_path.stat()為取得檔案的狀態資訊，例如大小、修改時間，.st_size是檔案的大小 單位是 Byte，1024是把 Byte 換算成 KB
    )

if __name__ == "__main__": # 執行上方的main程式
    main()