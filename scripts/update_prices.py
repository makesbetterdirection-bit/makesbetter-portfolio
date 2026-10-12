#!/usr/bin/env python3
"""MAKESBETTER.7 ver2 사이트용 prices.json 갱신 (GitHub Actions, 평일 07:50 KST = 전일 종가).

- 가격: 야후파이낸스 종목코드.KS, 마지막으로 마감된 거래일 종가(장중 실행 시 직전 거래일 종가).
- 분배율: FunETF 공개 API divBasic(로그인 불필요). 매월 지급 종목 = 최근 6회 월 분배율 평균×12,
  연 1~4회 지급 종목(NM) = 최근 1년 분배율 합계. 소수 1자리.
- 실패한 종목은 추정하지 않고 직전 파일 값 유지 + pending 기록. 값이 같으면 파일을 건드리지 않음.
stdlib 만 사용.
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone, date

KST = timezone(timedelta(hours=9))
# short 이름은 사이트 HTML의 PX / H.short 키와 같아야 한다
ETFS = [
    ("498400", "KODEX 200위클리CC"), ("480030", "ACE 미국500CC"), ("441640", "KODEX 미국배당CC"),
    ("0036R0", "RISE 휴머노이드"), ("494300", "KODEX 나스닥100CC"), ("0022T0", "SOL 금CC"),
    ("497570", "TIGER AI반도체"), ("485690", "RISE AI밸류체인"), ("473330", "SOL 30년국채CC"),
    ("332610", "PLUS 단기회사채"), ("488770", "KODEX 머니마켓"), ("182480", "TIGER 미국리츠(H)"),
]
NM = {"RISE 휴머노이드", "TIGER AI반도체", "RISE AI밸류체인", "KODEX 머니마켓"}  # 연 1~4회 지급
OUT = os.environ.get("PRICES_OUT", "prices.json")
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

def log(*a): print(*a, file=sys.stderr, flush=True)

def get(url, ua=None, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua or UAS[0], "Accept": "*/*", "Accept-Language": "ko,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode("utf-8", "ignore")
        except Exception as e: last = e; time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")

def isin(code):
    s = "KR7" + code + "00"
    d = "".join(str(int(c, 36)) for c in s); t = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 0: n *= 2; n = n - 9 if n > 9 else n
        t += n
    return s + str((10 - t % 10) % 10)

def yahoo_close(code):
    now = datetime.now(KST); last = None
    for ua in UAS:
        for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
            try:
                res = json.loads(get(f"https://{host}/v8/finance/chart/{code}.KS?range=1mo&interval=1d", ua=ua, tries=1))["chart"]["result"][0]
                bars = [(datetime.fromtimestamp(t, KST).date(), float(c)) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
                if not bars: raise RuntimeError("empty")
                # 장중(15:40 이전)에 찍힌 당일 봉은 미완성 → 직전 거래일 종가 사용
                if bars[-1][0] == now.date() and (now.hour, now.minute) < (15, 40) and len(bars) > 1: bars = bars[:-1]
                return bars[-1][0], round(bars[-1][1])
            except Exception as e: last = e
    raise RuntimeError(f"yahoo {code}: {last}")

def funetf_yield(code, short):
    d = json.loads(get(f"https://www.funetf.co.kr/api/public/product/view/divBasic?itemId={isin(code)}"))
    m = sorted((d.get("monthly") or []), key=lambda x: str(x["divDt"]))
    m = [x for x in m if x.get("divRt") is not None]
    if not m: raise RuntimeError(f"funetf {code}: no monthly")
    if short in NM:
        cutoff = (datetime.now(KST).date() - timedelta(days=365)).strftime("%Y%m%d")
        used = [x for x in m if str(x["divDt"]) >= cutoff]
        y = sum(float(x["divRt"]) for x in used)
    else:
        used = m[-6:]
        y = sum(float(x["divRt"]) for x in used) / len(used) * 12
    rng = (str(used[0]["divDt"]), str(used[-1]["divDt"])) if used else None
    return round(y, 1), rng

def main():
    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT, encoding="utf-8"))
        except Exception: prev = {}
    px, ys, pending, dates, rng6 = {}, {}, [], [], None
    for code, short in ETFS:
        try: dt, p = yahoo_close(code); px[short] = p; dates.append(dt)
        except Exception as e:
            log("price fail", short, e); pending.append(f"{short}:price")
            if short in (prev.get("px") or {}): px[short] = prev["px"][short]
        try:
            y, rng = funetf_yield(code, short); ys[short] = y
            if short == "ACE 미국500CC": rng6 = rng
        except Exception as e:
            log("yield fail", short, e); pending.append(f"{short}:yield")
            if short in (prev.get("y") or {}): ys[short] = prev["y"][short]
        time.sleep(0.4)
    asof = max(dates).isoformat() if dates else prev.get("asof")
    div_range = prev.get("divRange", "")
    if rng6:
        a, b = rng6; div_range = f"{a[:4]}.{int(a[4:6])}~{int(b[4:6])}월" if a[:4] == b[:4] else f"{a[:4]}.{int(a[4:6])}월~{b[:4]}.{int(b[4:6])}월"
    out = {"asof": asof, "px": px, "y": ys, "divRange": div_range,
           "divAsof": datetime.now(KST).date().isoformat(),
           "source": f"야후파이낸스 종가 · FunETF 분배금 지급 현황 · {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} KST 조회",
           "pending": pending}
    changed = any(out[k] != prev.get(k) for k in ("asof", "px", "y", "divRange"))
    if changed:
        json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"changed={'true' if changed else 'false'}")
    print(f"date={asof}")
    print(f"pending={','.join(pending) or 'none'}")
    log(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__": main()
