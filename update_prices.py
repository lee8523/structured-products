#!/usr/bin/env python3
"""
结构化票据行情自动更新脚本（收盘价版）
使用 akshare 获取：
  1) 各标的最近一个交易日的收盘价 → 注入 HTML 用于现价展示
  2) 各标的在产品期初日的收盘价 → 注入 HTML 用于定价计算

用法: python update_prices.py
首次使用请先安装依赖: pip install akshare
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

try:
    import akshare as ak
except ImportError:
    print("请先安装依赖: pip install akshare")
    sys.exit(1)

# 从 product_config.json 加载标的配置和产品映射
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "product_config.json")
with open(config_path, "r", encoding="utf-8") as f:
    _config = json.load(f)

UNDERLYINGS = _config["underlyings"]
PRODUCT_START_DATES = _config["product_start_dates"]
PRODUCT_UNDERLYING_MAP = _config["product_underlying_map"]


# ================================================================
# 辅助：从 DataFrame 按日期查找收盘价
# ================================================================

def find_close_by_date(df, target_date_str):
    """从带 date/date/日期 列的 DataFrame 中查找目标日期的收盘价"""
    # 找到日期列
    date_col = None
    for col in df.columns:
        cl = str(col).lower()
        if "日期" in cl or "date" in cl:
            date_col = col
            break
    if date_col is None:
        return None, None

    # 找到收盘列
    close_col = None
    for col in df.columns:
        cl = str(col).lower()
        if "收盘" in cl or cl == "close":
            close_col = col
            break
    if close_col is None:
        return None, None

    # 统一日期格式为字符串比较
    df["_date_str"] = df[date_col].astype(str).str[:10]
    target = target_date_str[:10]

    # 精确匹配
    matched = df[df["_date_str"] == target]
    if len(matched) > 0:
        price = float(matched.iloc[-1][close_col])
        return price, target

    # 找不到精确日期，取最接近的（前后7天内）
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d")
        best_diff = None
        best_price = None
        best_date = None
        for _, row in df.iterrows():
            try:
                row_dt = datetime.strptime(str(row["_date_str"]), "%Y-%m-%d")
                diff = abs((row_dt - target_dt).days)
                if diff <= 7 and (best_diff is None or diff < best_diff):
                    best_diff = diff
                    best_price = float(row[close_col])
                    best_date = str(row["_date_str"])
            except (ValueError, TypeError):
                continue
        if best_price and best_price > 0:
            return best_price, best_date
    except Exception:
        pass

    return None, None


# ================================================================
# 获取最新收盘价
# ================================================================

def fetch_latest_sge_gold():
    """SGE 黄金 AU9999 最新收盘价"""
    try:
        df = ak.spot_hist_sge(symbol="Au99.99")
        print(f"  [spot_hist_sge] 共 {len(df)} 行")
        last = df.iloc[-1]
        close_col = None
        for col in df.columns:
            if "收盘" in str(col).lower() or str(col).lower() == "close":
                close_col = col
                break
        if close_col:
            price = float(last[close_col])
            date_col = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), None)
            date_str = str(last[date_col])[:10] if date_col else "未知"
            if price > 100:
                print(f"  => AU9999 收盘: {price}  日期: {date_str}")
                return price, date_str
    except Exception as e:
        print(f"  [spot_hist_sge] 失败: {e}")
    return None, None


def fetch_latest_index(code):
    """指数最新收盘价"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
    try:
        df = ak.index_zh_a_hist(symbol=code, period="daily",
                                start_date=start, end_date=end)
        print(f"  [index_zh_a_hist] 共 {len(df)} 行")
        if len(df) > 0:
            last = df.iloc[-1]
            for col in ["收盘", "收盘价", "close", "Close"]:
                if col in df.columns:
                    price = float(last[col])
                    if price > 100:
                        date_str = str(last.get("日期", last.get("date", "")))[:10]
                        print(f"  => {code} 收盘: {price}  日期: {date_str}")
                        return price, date_str
    except Exception as e:
        print(f"  [index_zh_a_hist] 失败: {e}")

    # 备选: stock_zh_index_daily
    try:
        prefix = "sh" if code.startswith("000") else "sz"
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
        print(f"  [stock_zh_index_daily] 共 {len(df)} 行")
        if len(df) > 0:
            last = df.iloc[-1]
            for col in ["close", "收盘"]:
                if col in df.columns:
                    price = float(last[col])
                    if price > 100:
                        date_str = str(last.get("date", ""))[:10]
                        print(f"  => {code} 收盘: {price}  日期: {date_str}")
                        return price, date_str
    except Exception as e:
        print(f"  [stock_zh_index_daily] 失败: {e}")
    return None, None


def fetch_latest_futures(code):
    """期货最新收盘价"""
    try:
        df = ak.futures_zh_daily_sina(symbol=code)
        print(f"  [futures_zh_daily_sina] 共 {len(df)} 行")
        if len(df) > 0:
            last = df.iloc[-1]
            for col in ["close", "收盘"]:
                if col in df.columns:
                    price = float(last[col])
                    if price > 100:
                        date_str = str(last.get("date", ""))[:10]
                        print(f"  => {code} 收盘: {price}  日期: {date_str}")
                        return price, date_str
    except Exception as e:
        print(f"  [futures_zh_daily_sina] 失败: {e}")
    return None, None


# ================================================================
# 获取期初收盘价（产品成立日的收盘价）
# ================================================================

def fetch_initial_sge_gold(start_date):
    """SGE 黄金在指定日期的收盘价"""
    try:
        df = ak.spot_hist_sge(symbol="Au99.99")
        price, actual_date = find_close_by_date(df, start_date)
        if price:
            print(f"  => AU9999 期初价: {price}  日期: {actual_date}")
            return price
    except Exception as e:
        print(f"  [期初 spot_hist_sge] 失败: {e}")
    return None


def fetch_initial_index(code, start_date):
    """指数在指定日期的收盘价"""
    start_dt = datetime.strptime(start_date[:10], "%Y-%m-%d")
    s = (start_dt - timedelta(days=5)).strftime("%Y%m%d")
    e = (start_dt + timedelta(days=5)).strftime("%Y%m%d")
    try:
        df = ak.index_zh_a_hist(symbol=code, period="daily",
                                start_date=s, end_date=e)
        price, actual_date = find_close_by_date(df, start_date)
        if price:
            print(f"  => {code} 期初价: {price}  日期: {actual_date}")
            return price
    except Exception as e:
        print(f"  [期初 index_zh_a_hist] 失败: {e}")

    # 备选
    try:
        prefix = "sh" if code.startswith("000") else "sz"
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
        price, actual_date = find_close_by_date(df, start_date)
        if price:
            print(f"  => {code} 期初价: {price}  日期: {actual_date}")
            return price
    except Exception as e:
        print(f"  [期初 stock_zh_index_daily] 失败: {e}")
    return None


def fetch_initial_futures(code, start_date):
    """期货在指定日期的收盘价"""
    try:
        df = ak.futures_zh_daily_sina(symbol=code)
        price, actual_date = find_close_by_date(df, start_date)
        if price:
            print(f"  => {code} 期初价: {price}  日期: {actual_date}")
            return price
    except Exception as e:
        print(f"  [期初 futures_zh_daily_sina] 失败: {e}")
    return None


# ================================================================
# 主流程
# ================================================================

def main():
    print("=" * 50)
    print("  结构化票据行情更新（收盘价）")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(script_dir, "index.html")
    if not os.path.exists(html_path):
        html_path = os.path.join(script_dir, "structured-notes-dashboard.html")

    # ---- 1. 获取最新收盘价 ----
    print("\n[1/3] 获取最新收盘价...")
    latest_prices = {}
    for code, info in UNDERLYINGS.items():
        print(f"\n  [{info['name']}] ({code})")
        price, date_str = None, None
        try:
            if info["market"] == "sge":
                price, date_str = fetch_latest_sge_gold()
            elif info["market"] == "cn_index":
                price, date_str = fetch_latest_index(code)
            elif info["market"] in ("futures_gfex", "futures_shfe"):
                price, date_str = fetch_latest_futures(code)
        except Exception as e:
            print(f"  !! 异常: {e}")

        if price and price > 0:
            latest_prices[code] = {
                "price": price,
                "time": f"{date_str} 收盘" if date_str else datetime.now().strftime("%Y-%m-%d"),
            }
        else:
            print(f"  => 未获取到")

    # ---- 2. 获取各产品期初价 ----
    print("\n[2/3] 获取产品期初价...")
    initial_prices = {}
    for prod_code, start_date in PRODUCT_START_DATES.items():
        # 从配置中查找该产品对应的标的代码
        underlying_code = PRODUCT_UNDERLYING_MAP.get(prod_code)
        if not underlying_code or underlying_code not in UNDERLYINGS:
            print(f"\n  [{prod_code}] 未找到对应标的")
            continue
        market = UNDERLYINGS[underlying_code]["market"]

        info = UNDERLYINGS[underlying_code]
        print(f"\n  [{prod_code}] {info['name']} 期初日: {start_date}")

        price = None
        try:
            if market == "sge":
                price = fetch_initial_sge_gold(start_date)
            elif market == "cn_index":
                price = fetch_initial_index(underlying_code, start_date)
            elif market in ("futures_gfex", "futures_shfe"):
                price = fetch_initial_futures(underlying_code, start_date)
        except Exception as e:
            print(f"  !! 异常: {e}")

        if price and price > 0:
            initial_prices[prod_code] = price
        else:
            print(f"  => 未获取到期初价")

    # ---- 3. 汇总 & 注入 ----
    print("\n[3/3] 注入 HTML...")
    print(f"  最新价格: {len(latest_prices)} 个")
    for code, data in latest_prices.items():
        print(f"    {code}: {data['price']}  ({data['time']})")
    print(f"  期初价格: {len(initial_prices)} 个")
    for code, price in initial_prices.items():
        print(f"    {code}: {price}")

    if latest_prices or initial_prices:
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()

            # 构建注入数据
            inject_data = {
                "prices": latest_prices,
                "initial_prices": initial_prices,
            }
            js_data = json.dumps(inject_data, ensure_ascii=False, indent=None)
            injection = f"\n<script>window.__AUTO_PRICES__={js_data};</script>\n</head>"

            # 移除旧的注入块（兼容 </head> 和 <body> 两种锚点）
            html = re.sub(r"\n<script>window\.__AUTO_PRICES__=.*?</script>\s*\n?\s*(?=</head>|<body>)",
                          "", html, flags=re.DOTALL)

            # 优先注入到 </head> 前，找不到则注入到 <body> 前
            if "</head>" in html:
                html = html.replace("</head>", injection)
            elif "<body>" in html:
                html = html.replace("<body>", injection.rstrip("</head>") + "\n<body>")
            elif "<body" in html:
                # 兼容 <body class="..."> 等写法
                html = re.sub(r"(<body[^>]*>)", injection.rstrip("</head>") + r"\n\1", html, count=1)

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\n  已注入到 HTML: {html_path}")
        else:
            print(f"\n  HTML 文件未找到: {html_path}")

    print("\n完成! 打开 HTML 文件查看更新后的数据")
    import sys
    if sys.stdin.isatty():
        input("\n按回车键退出...")


if __name__ == "__main__":
    main()
