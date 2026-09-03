from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from typing import Dict, List

app = FastAPI(title="夜市即時營業與天氣 API")

# 允許 CORS 跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 14 大夜市營運資訊與縣市對照表
NIGHT_MARKETS = {
    "逢甲夜市": {"city": "臺中市", "schedule": "每天營業"},
    "一中街夜市": {"city": "臺中市", "schedule": "每天營業"},
    "旱溪夜市": {"city": "臺中市", "schedule": "週二、四、五、六"},
    "大東夜市": {"city": "臺南市", "schedule": "週一、二、五"},
    "花園夜市": {"city": "臺南市", "schedule": "週四、六、日"},
    "武聖夜市": {"city": "臺南市", "schedule": "週三、五、六"},
    "士林夜市": {"city": "臺北市", "schedule": "每天營業"},
    "饒河街夜市": {"city": "臺北市", "schedule": "每天營業"},
    "寧夏夜市": {"city": "臺北市", "schedule": "每天營業"},
    "樂華夜市": {"city": "新北市", "schedule": "每天營業"},
    "文化路夜市": {"city": "嘉義市", "schedule": "每天營業"},
    "瑞豐夜市": {"city": "高雄市", "schedule": "週二、四、五、六、日"},
    "六合夜市": {"city": "高雄市", "schedule": "每天營業"},
    "羅東夜市": {"city": "宜蘭縣", "schedule": "每天營業"}
}

# 記憶體資料庫：記錄民眾現場回報 (結構: {"夜市名稱": ["Open", "Few", "Closed"]})
REPORTS_DB: Dict[str, List[str]] = {}

class ReportRequest(BaseModel):
    market_name: str
    status: str  # 可選值: "Open", "Few", "Closed"

async def get_rain_probability(location_name: str) -> int:
    """呼叫中央氣象署 (CWA) 預報 API 取得降雨機率 ( PoP12h )"""
    cwa_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    params = {
        "Authorization": "CWA-8B1804E4-E5A7-466D-B07B-8B5BAA069324",
        "locationName": location_name
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(cwa_url, params=params, timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                location_data = data["record"]["location"][0]
                for element in location_data["weatherElement"]:
                    if element["elementName"] == "PoP":
                        return int(element["time"][0]["parameter"]["parameterName"])
        except Exception:
            pass
    return 0  # 若請求失敗預設回傳 0%

# ----------------- 路由設定 -----------------

@app.get("/")
def read_root():
    """使用者直接點擊網址時，自動呈現 index.html 頁面"""
    return FileResponse("index.html")

@app.get("/api/market/status")
async def get_market_status(name: str = Query(..., description="夜市名稱")):
    """查詢指定夜市的營業狀況、降雨機率與回報數據"""
    if name not in NIGHT_MARKETS:
        return {"error": "未找到該夜市資訊"}

    market_info = NIGHT_MARKETS[name]
    rain_prob = await get_rain_probability(market_info["city"])
    
    # 統計歷史回報
    reports = REPORTS_DB.get(name, [])
    report_count = len(reports)
    
    # 綜合評估顯示文字
    if rain_prob >= 70:
        status_text = "🌧️ 降雨機率高，建議攜帶雨具或注意攤位擺設"
    elif report_count > 0 and reports[-1] == "Closed":
        status_text = "🔴 民眾回報：現場沒開或攤位極少"
    else:
        status_text = "🟢 正常營業中"

    return {
        "market_name": name,
        "open_schedule": market_info["schedule"],
        "rain_probability": rain_prob,
        "recent_reports_count": report_count,
        "status": status_text
    }

@app.post("/api/market/report")
def submit_report(report: ReportRequest):
    """現場民眾打卡與營業狀況回報"""
    if report.market_name not in NIGHT_MARKETS:
        return {"error": "無效的夜市名稱"}
    
    if report.status not in ["Open", "Few", "Closed"]:
        return {"error": "無效的回報狀態"}

    if report.market_name not in REPORTS_DB:
        REPORTS_DB[report.market_name] = []
    
    REPORTS_DB[report.market_name].append(report.status)
    
    return {
        "message": "回報成功！感謝您提供現場資訊",
        "market_name": report.market_name,
        "total_reports": len(REPORTS_DB[report.market_name])
    }