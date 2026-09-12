"""
大山エリア 中古マンション3LDK 新着・値下げウォッチャー
- config.json に書いた検索URL(SUUMO / HOME'S / at home)を取得
- 前回結果(state.json)と比較して「新着」「値下げ」を抽出
- 3サイトの重複を統合して LINE に通知
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
CONFIG_FILE = "config.json"
JST = timezone(timedelta(hours=9))


# ---------- 共通ユーティリティ ----------
SITE_HOME = {
    "suumo": "https://suumo.jp/",
    "homes": "https://www.homes.co.jp/",
    "athome": "https://www.athome.co.jp/",
}


def fetch(url: str, referer: str | None = None) -> str | None:
    try:
        headers = {**HEADERS, "Referer": referer} if referer else HEADERS
        r = requests.get(url, headers=headers, timeout=30)
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
    """全角(３ＬＤＫ)も半角(3LDK)も判定できるよう正規化してから比較"""
    normalized = unicodedata.normalize("NFKC", text or "")
    return bool(re.search(r"3\s*LDK", normalized, re.I))


def first_image(img) -> str | None:
    """img要素から実際の画像URLを取り出す(遅延読み込みでsrcがダミーの場合に対応)"""
    if not img:
        return None
    for attr in ("data-original", "rel", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return v
    return None


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
        image = first_image(unit.select_one(".property_unit-object img"))
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
                "image": image,
            }
        )
    return out


def parse_homes(html: str, base: str) -> list[dict]:
    """
    HOME'S 専用パーサー。
    2種類のブロックが混在する: 単独物件カード(mod-listKks-sale)と、
    同一建物に複数戸ある場合の棟ブロック(mod-mergeBuilding--sale、内部に戸ごとの行を持つ)。
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []

    for card in soup.select("div.mod-listKks-sale.cMansion"):
        name_el = card.select_one(".bukkenName")
        link_el = card.select_one("a.detailLink")
        price_el = card.select_one("td.price .num")
        space_el = card.select_one("td.space")
        traffic_el = card.select_one("td.traffic")
        if not (name_el and link_el and price_el and space_el):
            continue
        space_text = space_el.get_text(" ", strip=True)
        if not is_3ldk(space_text):
            continue
        image = first_image(card.select_one(".bukkenPhoto img"))
        out.append(
            {
                "site": "HOME'S",
                "url": urljoin(base, link_el["href"]),
                "name": name_el.get_text(strip=True),
                "price": parse_price(price_el.get_text(strip=True) + "万円"),
                "area": parse_area(space_text),
                "layout": "3LDK",
                "built": "",
                "access": traffic_el.get_text(strip=True) if traffic_el else "",
                "image": image,
            }
        )

    for group in soup.select("div.mod-mergeBuilding--sale"):
        head_link = group.select_one("h3.heading a")
        name_el = group.select_one("h3.heading .bukkenName")
        if not (head_link and head_link.get("href") and name_el):
            continue
        building_url = urljoin(base, head_link["href"])
        building_name = name_el.get_text(strip=True)
        building_image = first_image(group.select_one(".bukkenPhoto img"))
        rows = group.select("table.unitSummary > tbody > tr[data-mbtg-alias='cMansion']")
        for i, row in enumerate(rows):
            info = {}
            for tr in row.select("table.verticalTable tr"):
                cells = tr.find_all(["th", "td"])
                for j in range(0, len(cells) - 1, 2):
                    info[cells[j].get_text(strip=True)] = cells[j + 1].get_text(" ", strip=True)
            layout = info.get("間取り", "")
            if not is_3ldk(layout):
                continue
            url = building_url if len(rows) == 1 else f"{building_url}#room{i + 1}"
            image = first_image(row.select_one(".displayPic img")) or building_image
            out.append(
                {
                    "site": "HOME'S",
                    "url": url,
                    "name": building_name,
                    "price": parse_price(info.get("価格", "")),
                    "area": parse_area(info.get("専有面積", "")),
                    "layout": layout,
                    "built": "",
                    "access": "",
                    "image": image,
                }
            )
    return out


def parse_athome(html: str, base: str) -> list[dict]:
    """at home 専用パーサー。各物件は div.card-box 単位で表示される。"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for card in soup.find_all("div", class_="card-box"):
        a = card.find("a", href=re.compile(r"^/mansion/\d+/"))
        if not a:
            continue
        titles = card.select(".title-wrap__title-text")
        name = titles[-1].get_text(strip=True) if titles else ""
        price_el = card.select_one(".property-price")
        info = {}
        for block in card.select(".property-detail-table__block"):
            strong, span = block.find("strong"), block.find("span")
            if strong and span:
                info[strong.get_text(strip=True)] = span.get_text(" ", strip=True)
        layout = info.get("間取り", "")
        if not is_3ldk(layout):
            continue
        image = first_image(card.select_one(".swiper-slide img"))
        out.append(
            {
                "site": "at home",
                "url": urljoin(base, a["href"].split("?")[0]),
                "name": name,
                "price": parse_price(price_el.get_text(" ", strip=True)) if price_el else None,
                "area": parse_area(info.get("専有面積", "")),
                "layout": unicodedata.normalize("NFKC", layout),
                "built": info.get("築年月", ""),
                "image": image,
                "access": info.get("交通", ""),
            }
        )
    return out


PARSERS = {
    "suumo": lambda html, url: parse_suumo(html, url),
    "homes": lambda html, url: parse_homes(html, url),
    "athome": lambda html, url: parse_athome(html, url),
}


# ---------- 重複統合 ----------
def dedupe_key(item: dict) -> str:
    """サイト横断の同一物件判定: 価格 + 面積(小数1桁) で近似"""
    area = f"{item['area']:.1f}" if item.get("area") else "?"
    return f"{item.get('price')}|{area}"


# ---------- 履歴 ----------
def norm_name(name: str) -> str:
    """棟名の正規化: 全角→半角、空白除去、号室や余計な語を落とす"""
    n = unicodedata.normalize("NFKC", name or "")
    n = re.sub(r"\s+", "", n)
    n = re.sub(r"(\d+階|\d+号室|部屋|中古マンション).*$", "", n)
    return n[:40] or "不明"


def update_history(current: dict, prev: dict) -> tuple[dict, list]:
    """
    掲載中の物件の価格推移を記録し、消えた物件を「掲載終了」にする。
    戻り値: (履歴全体, 今回消えた物件のリスト)
    """
    today = datetime.now(JST).strftime("%Y-%m-%d")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            hist = json.load(f)

    for url, it in current.items():
        h = hist.get(url)
        if h is None:
            h = {
                "name": it["name"],
                "building": norm_name(it["name"]),
                "site": it["site"],
                "area": it.get("area"),
                "built": it.get("built"),
                "first_seen": today,
                "prices": [],
                "status": "掲載中",
            }
            hist[url] = h
        if it.get("image"):
            h["image"] = it["image"]
        h["last_seen"] = today
        h["status"] = "掲載中"
        h.pop("ended", None)
        h.pop("days_listed", None)
        if it.get("price") and (not h["prices"] or h["prices"][-1]["price"] != it["price"]):
            h["prices"].append({"date": today, "price": it["price"]})

    ended = []
    for url in prev:
        h = hist.get(url)
        if url not in current and h and h.get("status") == "掲載中":
            h["status"] = "掲載終了"
            h["ended"] = today
            try:
                d0 = datetime.strptime(h["first_seen"], "%Y-%m-%d")
                h["days_listed"] = (datetime.strptime(today, "%Y-%m-%d") - d0).days
            except Exception:
                h["days_listed"] = None
            ended.append({**h, "url": url})

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    return hist, ended


def fmt_ended(h: dict) -> str:
    first = h["prices"][0]["price"] if h.get("prices") else None
    last = h["prices"][-1]["price"] if h.get("prices") else None
    line = f"・{h['name']}"
    if h.get("area"):
        line += f" {h['area']}㎡"
    if last:
        line += f"\n  最終 {last:,}万円"
        if first and first != last:
            line += f"（当初 {first:,}万円 / 値下げ{len(h['prices']) - 1}回）"
    if h.get("days_listed") is not None:
        line += f"\n  掲載 {h['days_listed']}日間 [{h['site']}]"
    return line


# ---------- 相場チェック（築年帯ごとに比較） ----------
# 掲載数が20件前後なので、細かく割ると各帯が1〜2件になり比較できない。
# まず粗い3区分で判定し、件数が増えてきたら config.json で細かくできる。
DEFAULT_BUCKETS = [
    ["築20年未満", 0, 20],
    ["築20〜35年", 20, 35],
    ["築35年以上", 35, 200],
]
MIN_PEERS = 3  # 同じ築年帯にこの件数未満しかなければ全体中央値にフォールバック
BUCKETS = DEFAULT_BUCKETS  # config.json の age_buckets で上書き


def unit_price(item: dict) -> float | None:
    """万円/㎡"""
    if item.get("price") and item.get("area"):
        return item["price"] / item["area"]
    return None


def built_year(built: str) -> int | None:
    """'2005年3月' や '築20年' から西暦を得る"""
    m = re.search(r"(\d{4})年", built or "")
    if m:
        return int(m.group(1))
    m = re.search(r"築(\d+)年", built or "")
    if m:
        return datetime.now(JST).year - int(m.group(1))
    return None


def age_bucket(item: dict, buckets=None) -> str:
    by = built_year(item.get("built", ""))
    if not by:
        return "築年不明"
    age = datetime.now(JST).year - by
    for name, lo, hi in (buckets or DEFAULT_BUCKETS):
        if lo <= age < hi:
            return name
    return "築年不明"


def median(vals: list[float]) -> float | None:
    vals = sorted(vals)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def bucket_medians(items: list[dict], buckets=None) -> dict:
    """
    築年帯ごとの㎡単価中央値。件数が足りない帯は載せない。
    "_all" に全体中央値を入れておき、フォールバック用に使う。
    """
    groups = {}
    all_vals = []
    for it in items:
        up = unit_price(it)
        if up:
            groups.setdefault(age_bucket(it, buckets), []).append(up)
            all_vals.append(up)
    out = {b: median(v) for b, v in groups.items() if len(v) >= MIN_PEERS and b != "築年不明"}
    if len(all_vals) >= MIN_PEERS:
        out["_all"] = median(all_vals)
    return out


def market_label(item: dict, meds: dict, buckets=None) -> str:
    up = unit_price(item)
    b = age_bucket(item, buckets)
    meds = meds or {}
    ref = meds.get(b)
    scope = f"{b}内"
    if not ref:
        ref = meds.get("_all")
        scope = "全体比・築年帯の件数不足"
    if not up or not ref:
        return " ⚪判定不可"
    diff = (up - ref) / ref * 100
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
    return f" {tag}({diff:+.0f}% / {scope})"


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


def fmt(item: dict, old_price: int | None = None, meds: dict | None = None) -> str:
    price = f"{item['price']:,}万円" if item.get("price") else "価格不明"
    if old_price:
        price = f"{old_price:,}→{item['price']:,}万円 (▼{old_price - item['price']:,})"
    area = f" {item['area']}㎡" if item.get("area") else ""
    built = f" {item['built']}" if item.get("built") else ""
    up = unit_price(item)
    up_s = f" @{up:.0f}万/㎡" if up else ""
    return f"・{item['name']}\n  {price}{area}{built}{up_s}{market_label(item, meds, BUCKETS)}\n  [{item['site']}] {item['url']}"


# ---------- メイン ----------
def main():
    global BUCKETS
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)
    BUCKETS = config.get("age_buckets") or DEFAULT_BUCKETS
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
            html = fetch(url, referer=SITE_HOME.get(site))
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

    hist, ended = update_history(current, prev)

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
    meds = bucket_medians(list(current.values()), BUCKETS)
    med_s = ("\n築年帯別 中央値: " + " / ".join(f"{b} {v:.0f}万" for b, v in sorted(meds.items()) if b != "_all")) if meds else ""
    lines = [f"🏠 大山 3LDK ウォッチ {today}", f"掲載中: {len(current)}件（3サイト合計）{med_s}"]
    if merged:
        lines.append(f"\n🆕 新着 {len(merged)}件")
        lines += [fmt(i, meds=meds) for i in merged]
    if price_drops:
        lines.append(f"\n📉 値下げ {len(price_drops)}件")
        lines += [fmt(i, old, meds) for i, old in price_drops]
    if ended:
        lines.append(f"\n🏁 掲載終了 {len(ended)}件（成約または取り下げ）")
        lines += [fmt_ended(h) for h in ended]
    if not merged and not price_drops and not ended:
        lines.append("\n本日の新着・値下げはありません")
    if errors:
        lines.append("\n⚠ " + " / ".join(errors))

    first_run = not prev
    if first_run:
        text = f"✅ 初回セットアップ完了。現在 {len(current)}件を記録しました。明日から差分を通知します。{med_s}"
        if errors:
            text += "\n⚠ " + " / ".join(errors)
        push_line(text)
    elif merged or price_drops or ended or config.get("notify_when_no_change", False):
        push_line("\n".join(lines))
    else:
        print("[info] 変化なし、通知スキップ")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
