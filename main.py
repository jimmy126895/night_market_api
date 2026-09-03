from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from datetime import datetime, timedelta
import uvicorn

app = FastAPI(title="Night Market Weather API")

# 設定 CORS 跨域，讓 index.html 網頁可以直接呼叫 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中央氣象署開放資料 API Key
CWA_API_KEY = "CWA-729A9210-D484-4F7C-A5B5-01B0E88F2AA2"

# 擴充後的全台熱門夜市資料庫
# open_days 說明: 0=週日, 1=週一, 2=週二, 3=週三, 4=週四, 5=週五, 6=週六
NIGHT_MARKETS = {
    # --- 臺北市 / 新北市 ---
    "ningxia": {
        "name": "寧夏夜市",
        "city": "臺北市",
        "district": "大同區",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    "shilin": {
        "name": "士林夜市",
        "city": "臺北市",
        "district": "士林區",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    "raohe": {
        "name": "饒河街夜市",
        "city": "臺北市",
        "district": "松山區",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    "lehua": {
        "name": "樂華夜市",
        "city": "新北市",
        "district": "永和區",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    # --- 臺中市 / 彰化縣 ---
    "fengjia": {
        "name": "逢甲夜市",
        "city": "臺中市",
        "district": "西屯區",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    "hanxi": {
        "name": "旱溪夜市",
        "city": "臺中市",
        "district": "東區",
        "open_days": [2, 4, 5, 6]  # 週二、四、五、六
    },
    "taichung_daqing": {
        "name": "大慶夜市",
        "city": "臺中市",
        "district": "南區",
        "open_days": [3, 5, 6, 0]  # 週三、五、六、日
    },
    "jingcheng": {
        "name": "精誠夜市",
        "city": "彰化縣",
        "district": "彰化市",
        "open_days": [3, 5, 6, 0]  # 週三、五、六、日
    },
    # --- 臺南市 / 高雄市 ---
    "dadong": {
        "name": "大東夜市",
        "city": "臺南市",
        "district": "東區",
        "open_days": [1, 2, 5]  # 週一、二、五
    },
    "huayuan": {
        "name": "花園夜市",
        "city": "臺南市",
        "district": "北區",
        "open_days": [4, 6, 0]  # 週四、六、日
    },
    "wusheng": {
        "name": "武聖夜市",
        "city": "臺南市",
        "district": "中西區",
        "open_days": [3, 5, 6]  # 週三、五、六
    },
    "ruifeng": {
        "name": "瑞豐夜市",
        "city": "高雄市",
        "district": "鼓山區",
        "open_days": [2, 4, 5, 6, 0]  # 週二、四、五、六、日
    },
    # --- 宜蘭縣 / 花蓮縣 ---
    "luodong": {
        "name": "羅東夜市",
        "city": "宜蘭縣",
        "district": "羅東鎮",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    },
    "dongdamen": {
        "name": "東大門夜市",
        "city": "花蓮縣",
        "district": "花蓮市",
        "open_days": [0, 1, 2, 3, 4, 5, 6]
    }
}

# 記憶體資料庫：儲存現場回報紀錄
REPORTS_DB = {}

# Pydantic 資料模型：定義前端發送回報時的格式
class UserReport(BaseModel):
    status: str  # "OPEN" (正常開), "FEW_STALLS" (攤位少), "CLOSED" (沒開)
    note: str = ""  # 備註說明


# --- API 1: 現場民眾打卡回報 ---
@app.post("/market/{market_id}/report")
async def report_market_status(market_id: str, report: UserReport):
    if market_id not in NIGHT_MARKETS:
        return {"error": "找不到該夜市"}
    
    if market_id not in REPORTS_DB:
        REPORTS_DB[market_id] = []
        
    report_entry = {
        "status": report.status,
        "note": report.note,
        "timestamp": datetime.now()
    }
    REPORTS_DB[market_id].append(report_entry)
    
    return {
        "message": "回報成功！感謝提供現場狀況",
        "data": {
            "status": report.status,
            "note": report.note,
            "time": report_entry["timestamp"].strftime("%H:%M:%S")
        }
    }


# --- API 2: 查詢夜市綜合狀態（氣象 + 群眾回報）---
@app.get("/market/{market_id}/status")
async def get_market_status(market_id: str):
    market = NIGHT_MARKETS.get(market_id)
    if not market:
        return {"error": "找不到該夜市"}

    # 1. 檢查今日固定營業日
    today_weekday = datetime.now().isoweekday() % 7
    is_open_today = today_weekday in market["open_days"]
    
    if not is_open_today:
        return {
            "name": market["name"],
            "status": "RED",
            "message": "今日固定公休",
            "rain_prob": 0,
            "user_reports_summary": "今日公休無現場回報",
            "recent_report_count": 0
        }

    # 2. 向中央氣象署 API 撈取降雨機率
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089"
    params = {
        "Authorization": CWA_API_KEY,
        "locationName": market["district"],
        "elementName": "PoP12h"
    }
    
    rain_prob = 0
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, params=params)
            data = res.json()
            
        for loc_group in data.get("records", {}).get("locations", []):
            for loc in loc_group.get("location", []):
                if loc["locationName"] == market["district"]:
                    for elem in loc.get("weatherElement", []):
                        if elem["elementName"] == "PoP12h":
                            val = elem["time"][0]["elementValue"][0]["value"]
                            rain_prob = int(val) if val.strip() else 0
                            break
    except Exception as e:
        print(f"API 讀取失敗: {e}")

    # 3. 統計過去 2 小時內的現場回報
    recent_reports = []
    two_hours_ago = datetime.now() - timedelta(hours=2)
    
    if market_id in REPORTS_DB:
        recent_reports = [
            r for r in REPORTS_DB[market_id] if r["timestamp"] >= two_hours_ago
        ]

    user_summary = "尚無近期現場回報"
    override_status = None
    
    if recent_reports:
        closed_count = sum(1 for r in recent_reports if r["status"] == "CLOSED")
        few_count = sum(1 for r in recent_reports if r["status"] == "FEW_STALLS")
        open_count = sum(1 for r in recent_reports if r["status"] == "OPEN")
        
        user_summary = f"近 2 小時共有 {len(recent_reports)} 筆回報（正常:{open_count}, 攤位少:{few_count}, 沒開:{closed_count}）"
        
        # 多數決邏輯（若有 2 筆以上的最新回報，權重高於氣象預報）
        if closed_count > open_count and closed_count >= 2:
            override_status = ("RED", "民眾回報：現場已打烊或沒開")
        elif few_count > open_count and few_count >= 2:
            override_status = ("YELLOW", "民眾回報：雨大，部分攤位已收攤")
        elif open_count >= 2:
            override_status = ("GREEN", "民眾回報：現場正常擺攤中")

    # 4. 綜合判定最終燈號
    if override_status:
        status, msg = override_status
    else:
        if rain_prob < 30:
            status, msg = "GREEN", "氣象顯示正常營業"
        elif rain_prob < 60:
            status, msg = "YELLOW", "降雨機率中等，建議攜帶雨具"
        else:
            status, msg = "RED", "降雨機率高，攤位可能減少或休市"

    return {
        "name": market["name"],
        "status": status,
        "message": msg,
        "rain_prob": rain_prob,
        "user_reports_summary": user_summary,
        "recent_report_count": len(recent_reports)
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
