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
        json_str = content[json_start:last_brace].strip()
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
    从黑猫投诉 (tousu.sina.cn) 抓取"演唱会退票"相关投诉数据。

    搜索页面可能会返回投诉总数或搜索结果数量。
    由于反爬机制，此函数可能无法获取数据，此时返回 None。

    返回值示例：
      {"totalComplaints": 57000} 或 None
    """
    print("[抓取] 正在从黑猫投诉获取数据...")
    result = {}

    try:
        # 黑猫投诉搜索接口
        search_url = "https://tousu.sina.cn/search"
        params = {
            "q": "演唱会退票",
            "type": "1",
        }
        resp = requests.get(
            search_url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # 尝试从页面中提取投诉总数
        # 黑猫投诉的搜索结果页通常包含类似 "共找到 XXXX 条结果" 的文本
        count_text = soup.find(string=re.compile(r"共.*?(\d+).*?条"))
        if count_text:
            count = safe_int(count_text)
            if count and count > 0:
                result["totalComplaints"] = count
                print(f"  -> 黑猫投诉搜索结果: {count} 条")

        # 尝试从搜索结果中提取各平台的投诉数量
        # 查找包含平台名称的投诉条目
        platform_keywords = {
            "大麦网": ["大麦", "damai"],
            "猫眼": ["猫眼", "maoyan"],
            "秀动": ["秀动", "showstart"],
            "淘票票": ["淘票票", "taopiaopiao"],
            "纷玩岛": ["纷玩岛"],
            "摩天轮票务": ["摩天轮"],
        }

        # 查找所有投诉卡片/列表项
        items = soup.select(".list-item, .search-result-item, .complaint-item, li")
        for item in items:
            text = item.get_text(strip=True)
            for platform, keywords in platform_keywords.items():
                if any(kw in text.lower() for kw in keywords):
                    # 尝试提取投诉数量（如果有）
                    # 这里的逻辑取决于页面结构，可能需要调整
                    pass

        if result:
            print(f"  -> 黑猫投诉数据获取成功: {result}")
        else:
            print("  -> 黑猫投诉: 未能提取到有效数据（可能被反爬拦截）")

    except requests.RequestException as e:
        print(f"  -> 黑猫投诉请求失败: {e}")
    except Exception as e:
        print(f"  -> 黑猫投诉解析失败: {e}")

    return result if result else None


def scrape_xiaofeibao():
    """
    从消费保 (xfb315.com) 抓取演唱会退票相关投诉数据。

    消费保是一个消费投诉平台，可能包含各票务平台的投诉统计。

    返回值示例：
      {"platforms": [...]} 或 None
    """
    print("[抓取] 正在从消费保获取数据...")
    result = {}

    try:
        # 消费保搜索页面
        search_url = "https://www.xfb315.com/search"
        params = {
            "keyword": "演唱会退票",
        }
        resp = requests.get(
            search_url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # 尝试提取投诉总数
        count_elements = soup.find_all(string=re.compile(r"\d+.*?条"))
        for elem in count_elements:
            count = safe_int(elem)
            if count and count > 100:  # 过滤掉过小的数字
                result["totalComplaints"] = count
                print(f"  -> 消费保投诉数量: {count}")
                break

        if result:
            print(f"  -> 消费保数据获取成功: {result}")
        else:
            print("  -> 消费保: 未能提取到有效数据")

    except requests.RequestException as e:
        print(f"  -> 消费保请求失败: {e}")
    except Exception as e:
        print(f"  -> 消费保解析失败: {e}")

    return result if result else None


def scrape_12315():
    """
    从12315投诉公示平台 (tsgs.12315.cn) 获取公开统计数据。

    12315首页通常会展示一些公开的统计信息，如投诉总量、调解率等。

    返回值示例：
      {"mediationRate": 62.52, "totalComplaintsCumulative": "14.79万件"} 或 None
    """
    print("[抓取] 正在从12315投诉公示平台获取数据...")
    result = {}

    try:
        base_url = "https://tsgs.12315.cn"
        resp = requests.get(
            base_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # 尝试提取页面中的统计数据
        # 12315首页可能包含调解率、投诉总量等信息
        page_text = soup.get_text(strip=True)

        # 尝试匹配调解率（百分比格式）
        mediation_match = re.search(r"调解[率成功率][：:\s]*(\d+\.?\d*)%?", page_text)
        if mediation_match:
            rate = safe_float(mediation_match.group(1))
            if rate:
                result["mediationRate"] = rate
                print(f"  -> 12315调解率: {rate}%")

        # 尝试匹配投诉总量（万件格式）
        total_match = re.search(r"(\d+\.?\d*)\s*万件", page_text)
        if total_match:
            result["totalComplaintsCumulative"] = f"{total_match.group(1)}万件"
            print(f"  -> 12315投诉总量: {total_match.group(1)}万件")

        # 尝试匹配金额（亿元格式）
        amount_match = re.search(r"(\d+\.?\d*)\s*亿", page_text)
        if amount_match:
            result["totalAmount"] = f"{amount_match.group(1)}亿+"
            print(f"  -> 12315涉及金额: {amount_match.group(1)}亿")

        if result:
            print(f"  -> 12315数据获取成功: {result}")
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
    updated = existing.copy()

    # 始终更新最后更新日期
    updated["lastUpdated"] = date.today().isoformat()

    # 合并黑猫投诉数据
    if heimao_data:
        if "totalComplaints" in heimao_data and heimao_data["totalComplaints"]:
            if "hero" not in updated:
                updated["hero"] = {}
            updated["hero"]["totalComplaints"] = heimao_data["totalComplaints"]

    # 合并消费保数据
    if xfb_data:
        if "totalComplaints" in xfb_data and xfb_data["totalComplaints"]:
            if "hero" not in updated:
                updated["hero"] = {}
            # 如果黑猫投诉也提供了数据，取较大值
            current = updated["hero"].get("totalComplaints", 0)
            if xfb_data["totalComplaints"] > current:
                updated["hero"]["totalComplaints"] = xfb_data["totalComplaints"]

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

    # 判断是否有实质性数据变更（排除 lastUpdated 字段）
    old_for_compare = {k: v for k, v in existing_data.items() if k != "lastUpdated"}
    new_for_compare = {k: v for k, v in updated_data.items() if k != "lastUpdated"}
    data_changed = old_for_compare != new_for_compare

    if data_changed:
        print("  -> 检测到数据变更，将更新 data.json")
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

    # 第五步：保存数据
    print("\n[步骤5] 保存数据...")
    save_data(updated_data)

    # 第六步：Git 提交和推送
    print("\n[步骤6] Git 操作...")
    git_commit_and_push(data_changed)

    print("\n" + "=" * 60)
    print("数据更新脚本执行完毕")
    print("=" * 60)


if __name__ == "__main__":
    main()
