"""TDX 共用前置工具：Token 管理、HTTP Session 建立與請求重試。"""

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TOKEN_CACHE = Path(".tdx_token.json")
SAFETY_MARGIN = 300 # 提前5分鐘判定 Token 過期，確保請求時有效

log = logging.getLogger("tdx")

def build_session() -> requests.Session:
    """建立具備指數退避重試機制的 HTTP Session"""
    retry = Retry(
        total = 3,
        backoff_factor = 2,
        status_forcelist = [429, 500, 502, 503, 504],
        allowed_methods = ["GET", "POST"],
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries = retry))
    return session

def _load_cached_token() -> str | None:
    """讀取 Token 快取，僅回傳仍在有效期限內的 Token"""
    if not TOKEN_CACHE.exists():
        return None
    try:
        cached = json.loads(TOKEN_CACHE.read_text())
    except json.JSONDecodeError:
        return None
    if cached.get("expires_at", 0) - SAFETY_MARGIN > time.time():
        log.info("使用快取的token")
        return cached["access_token"]
    return None

def get_token(session:requests.Session) -> str:
    """取得可用的 TDX Access Token，優先使用快取 Token"""
    cached = _load_cached_token()
    if cached:
        return cached

    log.info("向TDX申請新token")
    
    resp = session.post(
        AUTH_URL,
        data={
            "grant_type":"client_credentials",
            "client_id":os.environ["TDX_CLIENT_ID"],
            "client_secret":os.environ["TDX_CLIENT_SECRET"],
        },
        timeout = 15,
    )

    resp.raise_for_status()
    payload = resp.json()

    TOKEN_CACHE.write_text(json.dumps({
        "access_token":payload["access_token"],
        "expires_at":time.time() + payload.get("expires_in", 86400),
    }))

    log.info("取得新token 有效 %d 秒", payload.get("expires_in", 86400))
    return payload["access_token"]