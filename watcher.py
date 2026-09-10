"""
大山エリア 中古マンション3LDK 新着・値下げウォッチャー
- config.json に書いた検索URL(SUUMO / HOME'S / at home)を取得
- 前回結果(state.json)と比較して「新着」「値下げ」を抽出
- 3サイトの重複を統合して LINE に通知
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}
STATE_FILE = "state.json"
CONFIG_FILE = "config.json"
JST = timezone(timedelta(hours=9))


# ---------- 共通ユーティリティ ----------
def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"[warn] {url} -> HTTP {r.status_code}")
            return None
        return r.text
    except Exception as e:
        print(f"[warn] {url} -> {e}")
        return None


def parse_price(text: str) -> int | None:
    """'4,980万円' / '1億2,000万円' → 万円単位の整数"""
    if not text:
        return None
    t = text.replace(",", "").replace(" ", "")
    oku = re.search(r"(\d+)億", t)
    man = re.search(r"(\d+(?:\.\d+)?)万", t)
    total = 0
    if oku:
        total += int(oku.group(1)) * 10000
    if man:
        total += float(man.group(1))
    return int(total) if total else None


def parse_area(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|㎡|m2)", text or "")
    return float(m.group(1)) if m else None


def is_3ldk(text: str) -> bool:
    return bool(re.search(r"3\s*LDK", text or "", re.I))


# ---------- 各サイトのパーサー ----------
def parse_suumo(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for unit in soup.select("div.property_unit"):
        title_a = unit.select_one(".property_unit-title a")
        if not title_a:
            continue
        info = {}
        for dl in unit.select("dl"):
            dt, dd = dl.select_one("dt"), dl.select_one("dd")
            if dt and dd:
                info[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)
        layout = info.get("間取り", "")
        if not is_3ldk(layout):
            continue
        out.append(
            {
                "site": "SUUMO",
                "url": urljoin(base, title_a["href"]),
                "name": title_a.get_text(strip=True),
                "price": parse_price(info.get("販売価格", "")),
                "area": parse_area(info.get("専有面積", "")),
                "layout": layout,
                "built": info.get("築年月", ""),
                "access": info.get("沿線・駅", info.get("交通", "")),
            }
        )
    return out


def parse_generic(html: str, base: str, site: str, link_pattern: str) -> list[dict]:
    """
    HOME'S / at home 用のゆるいパーサー。
    物件詳細へのリンクを含むブロックごとに、テキストから価格・面積・間取りを拾う。
    サイト側のHTML変更に比較的強いが、精度はSUUMO専用パーサーより落ちる。
    """
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=re.compile(link_pattern)):
        url = urljoin(base, a["href"]).split("?")[0]
        if url in seen:
            continue
        # リンクを含む親ブロックを数段上まで遡ってテキストを集める
        block = a
        text = ""
        for _ in range(6):
            block = block.parent
            if block is None:
                break
            text = block.get_text(" ", strip=True)
            if "万円" in text and re.search(r"[LDK]", text):
                break
        if not is_3ldk(text):
            continue
        price = parse_price(re.search(r"(?:\d+億)?[\d,]+万円", text).group(0)) if re.search(
            r"(?:\d+億)?[\d,]+万円", text
        ) else None
        if price is None:
            continue
        seen.add(url)
        name = a.get_text(strip=True) or text[:40]
        built = ""
        m = re.search(r"(築\d+年|\d{4}年\d{1,2}月)", text)
        if m:
            built = m.group(1)
        out.append(
            {
                "site": site,
                "url": url,
                "name": name[:60],
                "price": price,
                "area": parse_area(text),
                "layout": "3LDK",
                "built": built,
                "access": "",
            }
        )
    return out


PARSERS = {
    "suumo": lambda html, url: parse_suumo(html, url),
    "homes": lambda html, url: parse_generic(html, url, "HOME'S", r"/mansion/b-\d+"),
    "athome": lambda html, url: parse_generic(html, url, "at home", r"/mansion/\d+/"),
}


# ---------- 重複統合 ----------
def dedupe_key(item: dict) -> str:
    """サイト横断の同一物件判定: 価格 + 面積(小数1桁) で近似"""
    area = f"{item['area']:.1f}" if item.get("area") else "?"
    return f"{item.get('price')}|{area}"


# ---------- 相場チェック ----------
def unit_price(item: dict) -> float | None:
    """万円/㎡"""
    if item.get("price") and item.get("area"):
        return item["price"] / item["area"]
    return None


def market_median(items: list[dict]) -> float | None:
    vals = sorted(v for v in (unit_price(i) for i in items) if v)
    if len(vals) < 3:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def market_label(item: dict, median: float | None) -> str:
    up = unit_price(item)
    if not up or not median:
        return ""
    diff = (up - median) / median * 100
    if diff <= -15:
        tag = "🟢割安"
    elif diff <= -5:
        tag = "🟢やや安"
    elif diff < 5:
        tag = "⚪相場並"
    elif diff < 15:
        tag = "🟠やや高"
    else:
        tag = "🔴割高"
    return f" {tag}({diff:+.0f}%)"


# ---------- LINE通知 ----------
def push_line(text: str):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not token or not user_id:
        print("[info] LINE設定なし。通知内容:\n" + text)
        return
    # LINEは1メッセージ5000文字上限
    chunks = [text[i : i + 4500] for i in range(0, len(text), 4500)]
    for chunk in chunks[:5]:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": user_id, "messages": [{"type": "text", "text": chunk}]},
            timeout=30,
        )
        print(f"[line] {r.status_code} {r.text[:200]}")


def fmt(item: dict, old_price: int | None = None, median: float | None = None) -> str:
    price = f"{item['price']:,}万円" if item.get("price") else "価格不明"
    if old_price:
        price = f"{old_price:,}→{item['price']:,}万円 (▼{old_price - item['price']:,})"
    area = f" {item['area']}㎡" if item.get("area") else ""
    built = f" {item['built']}" if item.get("built") else ""
    up = unit_price(item)
    up_s = f" @{up:.0f}万/㎡" if up else ""
    return f"・{item['name']}\n  {price}{area}{built}{up_s}{market_label(item, median)}\n  [{item['site']}] {item['url']}"


# ---------- メイン ----------
def main():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)
    prev = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            prev = json.load(f)

    current: dict[str, dict] = {}
    errors = []
    for site, urls in config["sources"].items():
        parser = PARSERS.get(site)
        if not parser:
            continue
        for url in urls:
            html = fetch(url)
            if not html:
                errors.append(f"{site}: 取得失敗")
                continue
            items = parser(html, url)
            print(f"[info] {site}: {len(items)}件")
            if not items:
                errors.append(f"{site}: 0件（HTML構造変更の可能性）")
            for it in items:
                current[it["url"]] = it
            time.sleep(3)  # サイトへの負荷を抑える

    # 差分
    new_items, price_drops = [], []
    for url, it in current.items():
        old = prev.get(url)
        if old is None:
            new_items.append(it)
        elif old.get("price") and it.get("price") and it["price"] < old["price"]:
            price_drops.append((it, old["price"]))

    # 新着のサイト横断重複を統合（既存物件と同キーなら新着扱いしない）
    prev_keys = {dedupe_key(v) for v in prev.values()}
    merged, seen_keys = [], set()
    for it in new_items:
        k = dedupe_key(it)
        if k in prev_keys or k in seen_keys:
            continue
        seen_keys.add(k)
        merged.append(it)

    today = datetime.now(JST).strftime("%m/%d")
    median = market_median(list(current.values()))
    med_s = f" / 相場中央値 {median:.0f}万円/㎡" if median else ""
    lines = [f"🏠 大山 3LDK ウォッチ {today}", f"掲載中: {len(current)}件（3サイト合計）{med_s}"]
    if merged:
        lines.append(f"\n🆕 新着 {len(merged)}件")
        lines += [fmt(i, median=median) for i in merged]
    if price_drops:
        lines.append(f"\n📉 値下げ {len(price_drops)}件")
        lines += [fmt(i, old, median) for i, old in price_drops]
    if not merged and not price_drops:
        lines.append("\n本日の新着・値下げはありません")
    if errors:
        lines.append("\n⚠ " + " / ".join(errors))

    first_run = not prev
    if first_run:
        text = f"✅ 初回セットアップ完了。現在 {len(current)}件を記録しました。明日から差分を通知します。{med_s}"
        if errors:
            text += "\n⚠ " + " / ".join(errors)
        push_line(text)
    elif merged or price_drops or config.get("notify_when_no_change", False):
        push_line("\n".join(lines))
    else:
        print("[info] 変化なし、通知スキップ")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
