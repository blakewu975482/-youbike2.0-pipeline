"""抓取 TDX YouBike 資料，選擇資料集、呼叫 API、驗證資料及儲存 JSON。"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv
from tdx import build_session, get_token

BASE = "https://tdx.transportdata.tw/api/basic/v2/Bike"
RAW_DIR = Path("data/raw")

# 集中管理各資料集的 API 設定、分區方式與必要欄位。
DATASETS = {
    "station":{
        "url": f"{BASE}/Station/City",
        "partition_by_hour": False,
        "required": {"StationUID", "StationName", "StationPosition", "BikesCapacity"}, 
    },
    "availability":{
        "url": f"{BASE}/Availability/City",
        "partition_by_hour": True,
        "required": {"StationUID", "AvailableRentBikes", "AvailableReturnBikes", "ServiceStatus"},
    },
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("fetch")

@click.command()
@click.option(
    "--dataset",
    type=click.Choice(list(DATASETS)),
    required=True
)
@click.option(
    "--city",
    default="Taichung",
    show_default=True
)
@click.option(
    "--show-keys",
    is_flag=True,
    help="只印出第一筆資料，用來確認回傳欄位與結構"
)

def main(dataset: str, city: str, show_keys: bool) -> None:
    load_dotenv()
    spec = DATASETS[dataset]
    fetched_at = datetime.now(timezone.utc)
    
    session = build_session()
    token = get_token(session)

    url = f"{spec['url']}/{city}"
    log.info("GET %s", url)
    resp = session.get(
        url,
        params={"$format": "JSON"},
        headers={
            "authorization": f"Bearer {token}",
            "accept-encoding": "gzip"
        },
        timeout=30,
    )
    resp.raise_for_status()
    records = resp.json()

    if not isinstance(records, list) or not records:
        raise SystemExit(f"API 回傳格式不符：預期是站點清單（JSON 陣列），實際拿到 {type(records).__name__}：{str(records)[:300]}")

    if show_keys:
        click.echo(json.dumps(records[0], ensure_ascii=False, indent=2))
        return

    missing = spec["required"] - set(records[0].keys())
    if missing:
        raise SystemExit(f"缺少欄位 {missing}\n實際欄位：{sorted(records[0])}")

    log.info("取得 %d 筆", len(records))

    # 依 UTC 日期分區儲存；即時資料再依 UTC 小時分區
    out_dir = RAW_DIR / dataset / f"city={city}" / f"dt={fetched_at:%Y-%m-%d}"
    if spec["partition_by_hour"]:
        out_dir = out_dir / f"hour={fetched_at:%H}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{fetched_at:%Y%m%dT%H%M%SZ}.json"
    out_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    log.info(
        "已寫入 %s (%.1f KB)",
        out_path,
        out_path.stat().st_size / 1024
    )

if __name__ == "__main__":
    main()