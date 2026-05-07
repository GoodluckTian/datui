#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大退网 (DaTuiWang) 数据更新脚本
================================
功能：
  1. 从公开数据源抓取最新的演唱会退票投诉数据
  2. 更新 data.json 文件
  3. 通过 git 提交并推送变更（CI 环境下跳过推送）

数据源：
  a. 黑猫投诉 (tousu.sina.cn) — 搜索"演唱会退票"获取投诉数量
  b. 消费保 (xfb315.com) — 获取各平台投诉数据
  c. 12315 投诉公示 (tsgs.12315.cn) — 获取公开统计数据

使用方式：
  python3 update_data.py

依赖：
  pip install requests beautifulsoup4
"""

import json
import os
import re
import subprocess
import sys
import hashlib
import time
import random
import string
import copy
from datetime import datetime, date

# ============================================================
# 依赖检查 — 如果缺少依赖库则给出提示并退出
# ============================================================
try:
    import requests
except ImportError:
    print("[错误] 缺少 requests 库，请运行: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[错误] 缺少 beautifulsoup4 库，请运行: pip install beautifulsoup4")
    sys.exit(1)


# ============================================================
# 全局配置
# ============================================================

# data.js 文件路径（与脚本同目录）
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.js")

# 请求超时时间（秒）
REQUEST_TIMEOUT = 15

# 通用请求头，模拟浏览器访问
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ============================================================
# 工具函数
# ============================================================

def safe_int(text, default=None):
    """
    从字符串中安全提取整数。
    如果提取失败则返回 default 值。
    """
    if text is None:
        return default
    try:
        # 移除逗号、空格等常见干扰字符
        cleaned = re.sub(r"[,\s，]", "", str(text))
        match = re.search(r"\d+", cleaned)
        if match:
            return int(match.group())
        return default
    except (ValueError, TypeError):
        return default


def safe_float(text, default=None):
    """
    从字符串中安全提取浮点数。
    如果提取失败则返回 default 值。
    """
    if text is None:
        return default
    try:
        cleaned = re.sub(r"[,\s，%]", "", str(text))
        match = re.search(r"[\d.]+", cleaned)
        if match:
            return float(match.group())
        return default
    except (ValueError, TypeError):
        return default


def load_data():
    """
    加载现有的 data.js 文件。
    通过提取 `const SITE_DATA = ` 和最后的 `};` 之间的 JSON 来解析。
    如果文件不存在则返回空字典。
    """
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # 提取 const SITE_DATA = ... ; 之间的 JSON 内容
        match = re.search(r"const\s+SITE_DATA\s*=\s*", content)
        if not match:
            print(f"[警告] {DATA_FILE} 中未找到 SITE_DATA 变量定义")
            return {}
        # 找到最后一个 };
        json_start = match.end()
        # 从 json_start 开始找到匹配的 }（处理嵌套对象）
        # 简单方法：找到最后一个 };
        last_brace = content.rfind("};")
        if last_brace == -1:
            print(f"[警告] {DATA_FILE} 中未找到有效的 JS 对象结尾")
            return {}
        json_str = content[json_start:last_brace + 1].strip()
        return json.loads(json_str)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[警告] 无法加载 {DATA_FILE}: {e}")
        return {}


def save_data(data):
    """
    将数据写入 data.js 文件，使用 JavaScript 变量赋值格式。
    输出格式: const SITE_DATA = { ... };
    """
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write("const SITE_DATA = ")
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write(";\n")
        print(f"[成功] 数据已保存到 {DATA_FILE}")
    except IOError as e:
        print(f"[错误] 无法写入 {DATA_FILE}: {e}")


# ============================================================
# 数据抓取模块
# ============================================================

def scrape_heimao():
    """
    从黑猫投诉 (tousu.sina.com.cn) 抓取"演唱会退票"相关投诉数据。

    使用签名算法调用搜索 API，获取投诉数量。
    签名算法：将 [ts, rs, "$d6eb7ff91ee257475%", keywords, page_size, page] 排序后拼接，SHA256。

    返回值示例：
      {"totalComplaints": 57000} 或 None
    """
    print("[抓取] 正在从黑猫投诉获取数据...")
    result = {}

    try:
        keywords = "演唱会退票"
        page_size = 10
        page = 1

        # 生成签名参数
        ts = str(int(time.time() * 1000))
        chars = string.ascii_letters + string.digits
        rs = ''.join(random.choice(chars) for _ in range(16))
        salt = "$d6eb7ff91ee257475%"

        parts = sorted([ts, rs, salt, keywords, str(page_size), str(page)])
        plaintext = ''.join(parts)
        signature = hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

        # 搜索 API
        search_url = "https://tousu.sina.com.cn/index/search/"
        params = {
            "keywords": keywords,
            "page_size": page_size,
            "page": page,
            "ts": ts,
            "rs": rs,
            "signature": signature,
        }
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://tousu.sina.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = requests.get(
            search_url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )

        # 检查是否被重定向到登录页
        if resp.status_code in (301, 302):
            print("  -> 黑猫投诉: 搜索需要登录，尝试备用方案...")

            # 备用方案：从首页获取累计投诉总量
            try:
                resp2 = requests.get(
                    "https://tousu.sina.com.cn/",
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                resp2.encoding = "utf-8"
                soup = BeautifulSoup(resp2.text, "html.parser")
                # 首页通常显示"累计有效投诉 XXXXX 条"
                page_text = soup.get_text()
                total_match = re.search(r"累计.*?(\d[\d,]+).*?投诉", page_text)
                if total_match:
                    total = safe_int(total_match.group(1))
                    if total and total > 1000:
                        result["totalComplaints"] = total
                        print(f"  -> 黑猫投诉累计投诉量: {total:,} 条")
            except Exception as e:
                print(f"  -> 黑猫投诉备用方案也失败: {e}")

            return result if result else None

        resp.raise_for_status()
        resp.encoding = "utf-8"

        # 解析 JSONP 响应
        text = resp.text
        # 去除 JSONP 包裹: try{jQuery...( 或直接 JSON
        json_match = re.search(r'\{.*"result".*\}', text, re.DOTALL)
        if not json_match:
            print("  -> 黑猫投诉: 返回数据格式无法解析")
            return None

        data = json.loads(json_match.group())

        if data.get("result", {}).get("status", {}).get("code") == 0:
            lists = data.get("result", {}).get("data", {}).get("lists", [])
            if lists:
                result["totalComplaints"] = len(lists)
                print(f"  -> 黑猫投诉搜索结果: 本页 {len(lists)} 条")

                # 尝试从标题中提取各平台投诉数量
                platform_counts = {}
                for item in lists:
                    title = item.get("main", {}).get("title", "")
                    for platform in ["大麦", "猫眼", "秀动", "淘票票", "纷玩岛", "摩天轮"]:
                        if platform in title:
                            platform_counts[platform] = platform_counts.get(platform, 0) + 1

                if platform_counts:
                    print(f"  -> 各平台提及次数: {platform_counts}")
        else:
            print("  -> 黑猫投诉: API 返回非成功状态")

    except requests.RequestException as e:
        print(f"  -> 黑猫投诉请求失败: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  -> 黑猫投诉解析失败: {e}")
    except Exception as e:
        print(f"  -> 黑猫投诉未知错误: {e}")

    return result if result else None


def scrape_xiaofeibao():
    """
    从消费保 (xfb315.com) 抓取各票务平台的投诉数据。

    使用官方 API (api.xfb315.com) 获取品牌统计数据。
    API: GET /brand/getBrandStatistics?brand_id={id}&type=all
    已知品牌ID：大麦网=18293, 猫眼=18295, 摩天轮票务=18319

    返回值示例：
      {"platforms": [{"name": "大麦网", "complaints": 105803, "resolveRate": "5.62%"}, ...]} 或 None
    """
    print("[抓取] 正在从消费保获取数据...")

    # 各票务平台的品牌ID
    brand_ids = {
        "大麦网": 18293,
        "猫眼": 18295,
        "摩天轮票务": 18319,
    }

    api_base = "https://api.xfb315.com/brand/getBrandStatistics"
    platforms_data = []

    for platform_name, brand_id in brand_ids.items():
        try:
            params = {"brand_id": brand_id, "type": "all"}
            headers = {
                "User-Agent": HEADERS["User-Agent"],
                "Referer": f"https://www.xfb315.com/brands/data_{brand_id}.html",
            }
            resp = requests.get(
                api_base,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200 and data.get("data"):
                    d = data["data"]
                    total = d.get("total")
                    solve_rate = d.get("solve_rate")

                    if total:
                        platforms_data.append({
                            "name": platform_name,
                            "complaints": total,
                            "resolveRate": f"{solve_rate}%" if solve_rate else "N/A",
                        })
                        print(f"  -> {platform_name}: 投诉量={total:,}, 解决率={solve_rate or 'N/A'}%")
                    else:
                        print(f"  -> {platform_name}: 无投诉量数据")
                else:
                    print(f"  -> {platform_name}: API 返回错误 - {data.get('msg', '未知')}")
            else:
                print(f"  -> {platform_name}: HTTP {resp.status_code}")

        except requests.RequestException as e:
            print(f"  -> {platform_name}: 请求失败 - {e}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  -> {platform_name}: 解析失败 - {e}")

    if platforms_data:
        return {"platforms": platforms_data}
    return None


def scrape_12315():
    """
    从12315投诉公示平台 (tsgs.12315.cn) 获取公开统计数据。

    使用官方 JSON API 接口：
      - threeRdsp: 热点商品/服务统计（含投诉量、调解成功率）
      - threeRdwt: 热点问题统计（含投诉量、调解成功率）
      - visitSearch: 网站访问量

    返回值示例：
      {"mediationRate": 62.52, "totalComplaintsCumulative": "14.79万件"} 或 None
    """
    print("[抓取] 正在从12315投诉公示平台获取数据...")
    result = {}

    base_api = "https://tsgs.12315.cn/zjtsgs_server"
    cache_buster = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

    try:
        # 1. 获取热点商品/服务统计（全国数据）
        api_url = f"{base_api}/ttsrdspfuCompute/threeRdsp"
        params = {"citycode": "XXXXXXXX", "_t": cache_buster}

        resp = requests.get(
            api_url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("state") == 200 and data.get("data"):
                    children = data["data"][0].get("children", [])
                    # 计算所有品类的总投诉量和平均调解率
                    total_count = 0
                    total_rate = 0
                    rate_count = 0
                    for item in children:
                        count = safe_int(item.get("gldCount"))
                        if count:
                            total_count += count
                        rate = safe_float(item.get("tstjcgl"))
                        if rate:
                            total_rate += rate
                            rate_count += 1

                    if total_count > 0:
                        # 将近30天数据推算为年度数据（粗略估算）
                        result["yearComplaints"] = total_count * 12
                        print(f"  -> 12315热点商品近30天投诉量: {total_count:,}")

                    if rate_count > 0:
                        avg_rate = round(total_rate / rate_count, 2)
                        result["mediationRate"] = avg_rate
                        print(f"  -> 12315平均调解成功率: {avg_rate}%")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"  -> 12315热点商品接口解析失败: {e}")

        # 2. 获取热点问题统计
        cache_buster2 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        api_url2 = f"{base_api}/ttsrdwtCompute/threeRdwt"
        params2 = {"citycode": "XXXXXXXX", "_t": cache_buster2}

        resp2 = requests.get(
            api_url2,
            params=params2,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if resp2.status_code == 200:
            try:
                data2 = resp2.json()
                if data2.get("state") == 200 and data2.get("data"):
                    children2 = data2["data"][0].get("children", [])
                    total_count2 = 0
                    for item in children2:
                        count = safe_int(item.get("gldCount"))
                        if count:
                            total_count2 += count

                    if total_count2 > 0:
                        # 合并到年度投诉量（避免重复计算，取较大值）
                        current = result.get("yearComplaints", 0)
                        estimated = total_count2 * 12
                        result["yearComplaints"] = max(current, estimated)
                        print(f"  -> 12315热点问题近30天投诉量: {total_count2:,}")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"  -> 12315热点问题接口解析失败: {e}")

        # 3. 获取网站访问量
        cache_buster3 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        api_url3 = f"{base_api}/tVisitsDomainLog/visitSearch"
        params3 = {"_t": cache_buster3}

        resp3 = requests.get(
            api_url3,
            params=params3,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if resp3.status_code == 200:
            try:
                data3 = resp3.json()
                if data3.get("state") == 200 and data3.get("data"):
                    visits = data3["data"]
                    total_visits = visits.get("C", 0)
                    if total_visits > 0:
                        print(f"  -> 12315网站总访问量: {total_visits:,}")
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        if result:
            print(f"  -> 12315数据获取成功: {list(result.keys())}")
        else:
            print("  -> 12315: 未能提取到有效数据")

    except requests.RequestException as e:
        print(f"  -> 12315请求失败: {e}")
    except Exception as e:
        print(f"  -> 12315解析失败: {e}")

    return result if result else None


# ============================================================
# 数据合并逻辑
# ============================================================

def merge_data(existing, heimao_data, xfb_data, data_12315):
    """
    将抓取到的新数据合并到现有数据中。

    合并规则：
      - 只有当新数据中某个字段存在且有效时，才会覆盖旧值
      - 如果某个数据源抓取失败（返回 None），则保留原有数据
      - lastUpdated 字段始终更新为当天日期
    """
    updated = copy.deepcopy(existing)

    # 始终更新最后更新日期
    updated["lastUpdated"] = date.today().isoformat()

    # 合并黑猫投诉数据
    if heimao_data:
        if "totalComplaints" in heimao_data and heimao_data["totalComplaints"]:
            if "hero" not in updated:
                updated["hero"] = {}
            updated["hero"]["totalComplaints"] = heimao_data["totalComplaints"]

    # 合并消费保数据（平台级别数据）
    if xfb_data and "platforms" in xfb_data:
        if "platforms" not in updated:
            updated["platforms"] = []
        # 更新已有平台的投诉量和解决率
        for new_p in xfb_data["platforms"]:
            found = False
            for old_p in updated["platforms"]:
                if old_p.get("name") == new_p.get("name"):
                    if new_p.get("complaints") is not None:
                        old_p["complaints"] = new_p["complaints"]
                        # 更新 barWidth（基于大麦网的比例）
                        max_complaints = max(
                            (p.get("complaints") for p in updated["platforms"] if p.get("complaints")),
                            default=1
                        )
                        old_p["barWidth"] = round(new_p["complaints"] / max_complaints * 100, 1) if max_complaints else 0
                    if new_p.get("resolveRate") and new_p["resolveRate"] != "N/A":
                        old_p["resolveRate"] = new_p["resolveRate"]
                    found = True
                    break
            if not found:
                updated["platforms"].append(new_p)

    # 合并12315数据
    if data_12315:
        if "mediationRate" in data_12315 and data_12315["mediationRate"]:
            if "overview" not in updated:
                updated["overview"] = {}
            updated["overview"]["mediationRate"] = data_12315["mediationRate"]

        if "totalComplaintsCumulative" in data_12315:
            if "overview" not in updated:
                updated["overview"] = {}
            updated["overview"]["totalComplaintsCumulative"] = data_12315["totalComplaintsCumulative"]

        if "totalAmount" in data_12315:
            if "overview" not in updated:
                updated["overview"] = {}
            updated["overview"]["totalAmount"] = data_12315["totalAmount"]

        if "yearComplaints" in data_12315 and data_12315["yearComplaints"]:
            if "overview" not in updated:
                updated["overview"] = {}
            updated["overview"]["yearComplaints"] = data_12315["yearComplaints"]

    return updated


# ============================================================
# Git 操作
# ============================================================

def git_commit_and_push(data_changed):
    """
    将变更提交到 git 并推送。

    如果没有实际数据变更（仅更新了时间戳），则不提交。
    如果在 CI 环境中运行（GITHUB_ACTIONS 环境变量存在），则跳过推送，
    让 GitHub Actions 自行处理提交和推送。
    """
    if not data_changed:
        print("[Git] 数据无实质性变更，跳过提交")
        return

    is_ci = os.environ.get("GITHUB_ACTIONS", "").lower() in ("true", "1", "yes")
    today = date.today().isoformat()

    try:
        # 添加 data.json 到暂存区
        subprocess.run(
            ["git", "add", DATA_FILE],
            check=True,
            capture_output=True,
            text=True,
        )

        # 提交变更
        commit_msg = f"数据更新: {today}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"[Git] 已提交: {commit_msg}")

        # CI 环境下跳过推送
        if is_ci:
            print("[Git] 检测到 CI 环境，跳过 git push（由 GitHub Actions 处理）")
        else:
            subprocess.run(
                ["git", "push"],
                check=True,
                capture_output=True,
                text=True,
            )
            print("[Git] 已推送到远程仓库")

    except subprocess.CalledProcessError as e:
        print(f"[Git] 操作失败: {e.stderr}")
    except FileNotFoundError:
        print("[Git] 未找到 git 命令，跳过版本控制操作")


# ============================================================
# 主函数
# ============================================================

def main():
    """
    主流程：
      1. 加载现有数据
      2. 从各数据源抓取新数据
      3. 合并数据
      4. 保存到 data.json
      5. 提交并推送变更
    """
    print("=" * 60)
    print(f"大退网数据更新脚本 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 第一步：加载现有数据
    print("\n[步骤1] 加载现有数据...")
    existing_data = load_data()
    if existing_data:
        print(f"  -> 已加载，上次更新日期: {existing_data.get('lastUpdated', '未知')}")
    else:
        print("  -> 未找到现有数据文件，将使用空数据")

    # 第二步：从各数据源抓取数据
    print("\n[步骤2] 开始抓取数据...")
    heimao_data = scrape_heimao()
    xfb_data = scrape_xiaofeibao()
    data_12315 = scrape_12315()

    # 汇总抓取结果
    sources_ok = sum(1 for d in [heimao_data, xfb_data, data_12315] if d is not None)
    print(f"\n[汇总] 数据源状态: {sources_ok}/3 个源返回了有效数据")

    # 第三步：合并数据
    print("\n[步骤3] 合并数据...")
    updated_data = merge_data(existing_data, heimao_data, xfb_data, data_12315)

    # 判断是否有实质性数据变更（排除 lastUpdated 和 history 字段）
    old_for_compare = {k: v for k, v in existing_data.items() if k not in ("lastUpdated", "history")}
    new_for_compare = {k: v for k, v in updated_data.items() if k not in ("lastUpdated", "history")}
    data_changed = old_for_compare != new_for_compare

    if data_changed:
        print("  -> 检测到数据变更，将更新 data.js")
    else:
        print("  -> 数据无实质性变更，仅更新时间戳")

    # 第四步：添加历史快照
    print("\n[步骤4] 添加历史快照...")
    today_str = date.today().isoformat()

    # 确保 history 数组存在
    if "history" not in updated_data:
        updated_data["history"] = []

    # 检查今天是否已有记录，避免重复
    today_exists = any(h.get("date") == today_str for h in updated_data["history"])
    if not today_exists:
        # 创建今天的简化快照
        snapshot = {
            "date": today_str,
            "hero": {
                "totalComplaints": updated_data.get("hero", {}).get("totalComplaints")
            },
            "platforms": [
                {"name": p["name"], "complaints": p.get("complaints")}
                for p in updated_data.get("platforms", [])
                if p.get("complaints") is not None
            ]
        }
        updated_data["history"].append(snapshot)
        print(f"  -> 已添加 {today_str} 的历史快照")
    else:
        print(f"  -> {today_str} 已有历史记录，跳过")

    # 保留最近365天的历史记录
    if len(updated_data["history"]) > 365:
        updated_data["history"] = updated_data["history"][-365:]
        print(f"  -> 历史记录已裁剪至最近365天")

    # 检查 history 是否有变更
    old_history = existing_data.get("history", [])
    new_history = updated_data.get("history", [])
    history_changed = len(old_history) != len(new_history)

    # 第五步：保存数据
    print("\n[步骤5] 保存数据...")
    save_data(updated_data)

    # 第六步：Git 提交和推送
    print("\n[步骤6] Git 操作...")
    git_commit_and_push(data_changed or history_changed)

    print("\n" + "=" * 60)
    print("数据更新脚本执行完毕")
    print("=" * 60)


if __name__ == "__main__":
    main()
