"""
state.json / history.json から docs/index.html を生成する。
GitHub Pages で公開すると、スマホからいつでも見られるダッシュボードになる。
外部APIは使わず、自分で集めたデータだけで作る。
"""
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
OUT = "docs/index.html"


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


DEFAULT_BUCKETS = [["築20年未満", 0, 20], ["築20〜35年", 20, 35], ["築35年以上", 35, 200]]
MIN_PEERS = 3


def unit(price, area):
    return round(price / area, 1) if price and area else None


def built_year(built: str):
    m = re.search(r"(\d{4})年", built or "")
    if m:
        return int(m.group(1))
    m = re.search(r"築(\d+)年", built or "")
    if m:
        return datetime.now(JST).year - int(m.group(1))
    return None


def age_bucket(built: str, buckets):
    by = built_year(built)
    if not by:
        return "築年不明"
    age = datetime.now(JST).year - by
    for name, lo, hi in buckets:
        if lo <= age < hi:
            return name
    return "築年不明"


def main():
    state = load("state.json", {})
    hist = load("history.json", {})
    now = datetime.now(JST)

    # ---- 掲載中（築年帯ごとに割安判定） ----
    cfg = load("config.json", {})
    buckets = cfg.get("age_buckets") or DEFAULT_BUCKETS

    groups = {}
    units = []
    for it in state.values():
        u = unit(it.get("price"), it.get("area"))
        if u:
            groups.setdefault(age_bucket(it.get("built", ""), buckets), []).append(u)
            units.append(u)
    meds = {b: round(statistics.median(v), 1)
            for b, v in groups.items() if len(v) >= MIN_PEERS and b != "築年不明"}
    counts = {b: len(v) for b, v in groups.items()}
    overall = round(statistics.median(units), 1) if len(units) >= MIN_PEERS else None

    listings = []
    for url, it in state.items():
        h = hist.get(url, {})
        u = unit(it.get("price"), it.get("area"))
        b = age_bucket(it.get("built", ""), buckets)
        ref, scope = meds.get(b), b + "内"
        if ref is None:
            ref, scope = overall, "全体比"
        prices = h.get("prices", [])
        listings.append({
            **it,
            "unit": u,
            "bucket": b,
            "scope": scope,
            "ref": ref,
            "pct": round((u - ref) / ref * 100) if (u and ref) else None,
            "first_seen": h.get("first_seen", ""),
            "cuts": max(0, len(prices) - 1),
            "initial": prices[0]["price"] if prices else None,
        })
    listings.sort(key=lambda x: (x["bucket"], x["pct"] if x["pct"] is not None else 999))

    # ---- 掲載終了 ----
    ended = []
    for url, h in hist.items():
        if h.get("status") != "掲載終了":
            continue
        prices = h.get("prices", [])
        ended.append({
            **h, "url": url,
            "initial": prices[0]["price"] if prices else None,
            "final": prices[-1]["price"] if prices else None,
            "cuts": max(0, len(prices) - 1),
        })
    ended.sort(key=lambda x: x.get("ended", ""), reverse=True)

    days = [e["days_listed"] for e in ended if e.get("days_listed") is not None]
    cut_rate = round(sum(1 for e in ended if e["cuts"]) / len(ended) * 100) if ended else None
    drops = [
        round((e["initial"] - e["final"]) / e["initial"] * 100, 1)
        for e in ended if e.get("initial") and e.get("final") and e["initial"] > e["final"]
    ]

    # ---- 棟別 ----
    buildings = defaultdict(list)
    for url, h in hist.items():
        buildings[h.get("building", "不明")].append({**h, "url": url})
    bld = []
    for name, items in buildings.items():
        items.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
        bld.append({
            "name": name,
            "items": items,
            "active": sum(1 for i in items if i.get("status") == "掲載中"),
            "total": len(items),
        })
    bld.sort(key=lambda x: (-x["active"], -x["total"]))

    # ---- 掲載件数の推移（日次） ----
    seen_days = sorted({d for h in hist.values() for d in [h.get("first_seen"), h.get("last_seen")] if d})
    timeline = []
    for d in seen_days:
        n = sum(1 for h in hist.values()
                if h.get("first_seen", "9") <= d <= (h.get("ended") or h.get("last_seen") or "0"))
        timeline.append({"date": d, "n": n})

    data = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "median": overall,
        "meds": meds,
        "counts": counts,
        "bucket_order": [b[0] for b in buckets] + ["築年不明"],
        "listings": listings,
        "ended": ended,
        "buildings": bld,
        "timeline": timeline,
        "stats": {
            "n_active": len(state),
            "n_ended": len(ended),
            "avg_days": round(statistics.mean(days)) if days else None,
            "cut_rate": cut_rate,
            "avg_drop": round(statistics.mean(drops), 1) if drops else None,
        },
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    print(f"[info] {OUT} 生成: 掲載中{len(listings)} / 掲載終了{len(ended)} / 棟{len(bld)}")


HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>大山 中古3LDK 定点観測</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e2dc;--g:#1e8a4c;--o:#c8791b;--r:#b8302f}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.6}
header{padding:20px 16px 10px}h1{font-size:19px;margin:0}.sub{color:var(--mute);font-size:12px;margin-top:4px}
.tabs{display:flex;gap:6px;padding:0 12px}
.tabs button{flex:1;padding:9px 4px;border:1px solid var(--line);background:var(--card);border-radius:8px;font-size:13px;font-family:inherit}
.tabs button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
section{margin:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
h2{font-size:15px;margin:0 0 10px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px;margin-bottom:12px}
.kpi{background:var(--bg);border-radius:8px;padding:9px}.kpi b{display:block;font-size:18px}.kpi span{font-size:11px;color:var(--mute)}
.card{display:flex;gap:10px;border-top:1px solid var(--line);padding:11px 0}.card:first-child{border-top:0}
.card .thumb{flex:none;width:84px;height:63px;border-radius:8px;object-fit:cover;background:var(--bg)}
.card .body{min-width:0;flex:1}
.name{font-weight:600}.price{font-size:17px;font-weight:700;margin-top:3px}
.meta{color:var(--mute);font-size:12px;margin-top:3px}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:99px;color:#fff;margin-left:6px;white-space:nowrap}
.g{background:var(--g)}.o{background:var(--o)}.r{background:var(--r)}.n{background:#8a8a85}
.small{font-size:12px;color:var(--mute)}
a{color:inherit}
details{border-top:1px solid var(--line)}details summary{cursor:pointer;padding:9px 0;font-weight:600}
.hist{font-size:12px;color:var(--mute);margin:0 0 8px 12px}
.hide{display:none}
</style></head><body>
<header><h1>🏠 大山 中古3LDK 定点観測</h1><div class="sub" id="sub"></div></header>
<div class="tabs">
 <button class="on" data-t="t1">掲載中</button>
 <button data-t="t2">掲載終了</button>
 <button data-t="t3">棟別</button>
</div>

<section id="t1">
 <div class="kpis" id="k1"></div>
 <canvas id="tl" height="180"></canvas>
 <h2 style="margin-top:14px">掲載中の物件（割安順）</h2>
 <p class="small">判定は<b>同じ築年帯の物件どうし</b>の㎡単価比較。築浅タワーと築古が混ざらないようにしています。同じ帯が3件未満のときは全体比に切り替わり、その旨を表示します。</p>
 <div id="meds" class="small" style="margin-bottom:8px"></div>
 <div id="listings"></div>
</section>

<section id="t2" class="hide">
 <div class="kpis" id="k2"></div>
 <h2>掲載が終わった物件</h2>
 <p class="small">サイトから消えた＝成約か取り下げ。どちらかは分かりませんが、価格の妥当性を測る手がかりになります。</p>
 <div id="ended"></div>
</section>

<section id="t3" class="hide">
 <h2>棟ごとの売出・値下げ履歴</h2>
 <p class="small">同じ棟から繰り返し売りが出るかどうかは、管理状態や住み心地のヒントになります。</p>
 <div id="bld"></div>
</section>

<script>
const D = __DATA__;
const yen = v => v == null ? '-' : v.toLocaleString() + '万円';
document.getElementById('sub').textContent = `更新 ${D.generated}`;

document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  ['t1','t2','t3'].forEach(t => document.getElementById(t).classList.toggle('hide', t !== b.dataset.t));
});

const tag = p => p == null ? '<span class="tag n">判定不可</span>'
  : p <= -15 ? `<span class="tag g">割安 ${p}%</span>`
  : p <= -5  ? `<span class="tag g">やや安 ${p}%</span>`
  : p < 5    ? `<span class="tag n">相場並 ${p>0?'+':''}${p}%</span>`
  : p < 15   ? `<span class="tag o">やや高 +${p}%</span>`
  :            `<span class="tag r">割高 +${p}%</span>`;

const S = D.stats;
document.getElementById('k1').innerHTML = [
  [S.n_active + '件', '掲載中（3サイト）'],
  [Object.keys(D.meds).length + '帯', '築年帯別に判定中'],
  [S.n_ended + '件', '掲載終了（累計）'],
].map(([b, s]) => `<div class="kpi"><b>${b}</b><span>${s}</span></div>`).join('');

document.getElementById('k2').innerHTML = [
  [S.avg_days != null ? S.avg_days + '日' : '—', '平均掲載期間'],
  [S.cut_rate != null ? S.cut_rate + '%' : '—', '値下げした割合'],
  [S.avg_drop != null ? '▼' + S.avg_drop + '%' : '—', '平均値下げ幅'],
].map(([b, s]) => `<div class="kpi"><b>${b}</b><span>${s}</span></div>`).join('');

if (D.timeline.length > 1) {
  new Chart(document.getElementById('tl'), {
    type: 'line',
    data: { labels: D.timeline.map(t => t.date.slice(5)),
      datasets: [{ label: '掲載件数', data: D.timeline.map(t => t.n),
        borderColor: '#1d1d1b', backgroundColor: 'rgba(30,138,76,.08)', fill: true, tension: .3 }] },
    options: { plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, title: { display: true, text: '掲載件数' } } } }
  });
} else {
  document.getElementById('tl').outerHTML = '<p class="small">推移グラフは数日分たまると表示されます。</p>';
}

document.getElementById('meds').innerHTML = D.bucket_order
  .filter(b => D.counts[b])
  .map(b => `${b} <b>${D.meds[b] ? D.meds[b] + '万/㎡' : '—'}</b>（${D.counts[b]}件）`)
  .join(' ・ ') + (D.median ? ` ／ 全体 ${D.median}万/㎡` : '');

const thumb = src => src
  ? `<img class="thumb" src="${src}" loading="lazy" alt="" onerror="this.remove()">`
  : '';

const byBucket = {};
D.listings.forEach(l => (byBucket[l.bucket] = byBucket[l.bucket] || []).push(l));
document.getElementById('listings').innerHTML = D.bucket_order
  .filter(b => byBucket[b])
  .map(b => `<h3 style="font-size:13px;color:var(--mute);margin:16px 0 0">${b}（${byBucket[b].length}件）</h3>` +
    byBucket[b].map(l => `<div class="card">
 ${thumb(l.image)}
 <div class="body">
  <div class="name"><a href="${l.url}" target="_blank">${l.name}</a>${tag(l.pct)}</div>
  <div class="price">${yen(l.price)} <span class="small">${l.unit ? '@' + l.unit + '万/㎡' : ''}</span></div>
  <div class="meta">${l.area ? l.area + '㎡ ' : ''}${l.built || ''} [${l.site}] / 比較 ${l.scope}${l.ref ? ' ' + l.ref + '万/㎡' : ''}${l.first_seen ? ' / 初掲載 ' + l.first_seen : ''}${l.cuts ? ` / 値下げ${l.cuts}回（当初 ${yen(l.initial)}）` : ''}</div>
 </div>
</div>`).join('')).join('') || '<p class="small">まだデータがありません。</p>';

document.getElementById('ended').innerHTML = D.ended.map(e => `<div class="card">
 ${thumb(e.image)}
 <div class="body">
  <div class="name">${e.name}</div>
  <div class="price">${yen(e.final)}${e.initial && e.initial !== e.final ? ` <span class="small">当初 ${yen(e.initial)}（▼${(100-e.final/e.initial*100).toFixed(1)}%）</span>` : ''}</div>
  <div class="meta">${e.area ? e.area + '㎡ ' : ''}${e.built || ''} [${e.site}] / ${e.first_seen} 〜 ${e.ended}${e.days_listed != null ? `（${e.days_listed}日）` : ''}${e.cuts ? ` / 値下げ${e.cuts}回` : ''}</div>
 </div>
</div>`).join('') || '<p class="small">掲載終了した物件はまだありません。数週間たつと出てきます。</p>';

document.getElementById('bld').innerHTML = D.buildings.map(b => `<details>
 <summary>${b.name} <span class="small">掲載中${b.active} / 累計${b.total}</span></summary>
 ${b.items.map(i => `<div class="hist">
   <a href="${i.url}" target="_blank">${i.area ? i.area + '㎡ ' : ''}${i.built || ''} [${i.site}]</a> — ${i.status}${i.ended ? '（' + i.ended + '）' : ''}<br>
   ${(i.prices || []).map(p => `${p.date.slice(5)} ${yen(p.price)}`).join(' → ') || '価格記録なし'}
 </div>`).join('')}
</details>`).join('') || '<p class="small">まだデータがありません。</p>';
</script></body></html>
"""

if __name__ == "__main__":
    main()
