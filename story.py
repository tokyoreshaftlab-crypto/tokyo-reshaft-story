"""
東京リシャフトラボ ストーリーズ OPEN 自動投稿

  python story.py render [YYYY-MM-DD]   画像だけ作る（out/ に保存）
  python story.py post                  今日の画像を作ってストーリーズに投稿
  python story.py refresh               アクセストークンを更新して新しいトークンを出力

投稿に必要な環境変数:
  IG_ACCESS_TOKEN   Instagram の長期アクセストークン
  IMAGE_BASE_URL    out/ の画像を公開しているURLの頭（GitHub Actions が自動で設定）
"""
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
PHOTOS = ROOT / "photos"
OUT = ROOT / "out"
FONT = ROOT / "fonts" / "InterDisplay-Bold.otf"
JST = dt.timezone(dt.timedelta(hours=9))
API = "https://graph.instagram.com/v25.0"
W, H = 1080, 1920
WHITE = (245, 242, 236)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# レイアウト: (名前, 文字の基準x, 基準y, 揃え)  ※ストーリーズのアイコン/返信欄に隠れない範囲
LAYOUTS = {
    1: ("左上", 80, 330, "l"),
    2: ("左下", 80, 1500, "l"),
    3: ("中央", 540, 960, "c"),
    4: ("右下", 1000, 1500, "r"),
    5: ("下中央＋線", 540, 1500, "c"),
}


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def photo_list():
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(p.name for p in PHOTOS.iterdir() if p.suffix.lower() in exts)


# ---------- その日の写真とレイアウトを決める（毎回同じ日なら同じ結果） ----------
def _day_number(day):
    return (day - dt.date(2026, 1, 1)).days


def _photo_for(day, photos):
    n = len(photos)
    d = _day_number(day)
    order = photos[:]
    random.Random(f"cycle-{d // n}").shuffle(order)
    return order[d % n]


def _layout_for(day, photo, cfg, prev_layout=None):
    banned = set(cfg.get("layout_rules", {}).get(photo, []))
    allowed = [k for k in LAYOUTS if k not in banned] or list(LAYOUTS)
    if prev_layout in allowed and len(allowed) > 1:
        allowed.remove(prev_layout)
    return random.Random(f"layout-{day.isoformat()}").choice(allowed)


def choose(day, cfg):
    """基準日から1日ずつ順にたどり、前日と同じ写真・同じレイアウトにならないよう決める"""
    photos = photo_list()
    if not photos:
        raise SystemExit("photos フォルダに写真がありません")
    anchor = dt.date(2026, 10, 1)
    prev_photo, prev_layout = None, None
    d = min(anchor, day)
    while True:
        photo = _photo_for(d, photos)
        if photo == prev_photo and len(photos) > 1:
            photo = photos[(photos.index(photo) + 1) % len(photos)]
        layout = _layout_for(d, photo, cfg, prev_layout)
        if d == day:
            return photo, layout
        if not is_closed(d, cfg):  # 投稿しない日は「前回」に数えない
            prev_photo, prev_layout = photo, layout
        d += dt.timedelta(days=1)


# ---------- 画像合成 ----------
def _soft_shadow(im, cx, cy, r=520, alpha=150):
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    steps = 40
    for i in range(steps):
        rr = r * (1 - i / steps)
        d.ellipse([cx - rr, cy - rr * 0.6, cx + rr, cy + rr * 0.6], fill=int(alpha * i / steps))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, mask)


def render(day, cfg):
    photo, layout = choose(day, cfg)
    _, x, y, align = LAYOUTS[layout]
    im = ImageOps.exif_transpose(Image.open(PHOTOS / photo)).convert("RGB")
    im = ImageOps.fit(im, (W, H), Image.LANCZOS)

    text = cfg.get("text", "OPEN")
    size = int(cfg.get("font_size", 110))
    track = int(cfg.get("letter_spacing", 14))
    font = ImageFont.truetype(str(FONT), size)
    probe = ImageDraw.Draw(im)
    widths = [probe.textlength(c, font=font) for c in text]
    total = sum(widths) + track * (len(text) - 1)
    start = {"l": x, "c": x - total / 2, "r": x - total}[align]

    im = _soft_shadow(im, start + total / 2, y)
    d = ImageDraw.Draw(im)
    cx = start
    for c, w in zip(text, widths):
        d.text((cx, y), c, font=font, fill=WHITE, anchor="lm")
        cx += w + track
    if layout == 5:
        d.line([(540 - 60, y - 90), (540 + 60, y - 90)], fill=WHITE, width=4)

    OUT.mkdir(exist_ok=True)
    out = OUT / f"{day.strftime('%Y%m%d')}.jpg"
    im.save(out, "JPEG", quality=92)  # Instagram API は JPEG のみ対応
    return out, photo, layout


def cleanup(cfg, today):
    keep = int(cfg.get("keep_history_days", 14))
    for f in OUT.glob("*.jpg"):
        try:
            d = dt.datetime.strptime(f.stem, "%Y%m%d").date()
        except ValueError:
            continue
        if (today - d).days > keep:
            f.unlink()


def is_closed(day, cfg):
    if WEEKDAYS[day.weekday()] in cfg.get("closed_weekdays", []):
        return "定休日"
    if day.isoformat() in cfg.get("skip_dates", []):
        return "休業日（skip_dates）"
    return None


# ---------- Instagram API ----------
def _call(method, url, params):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # トークンを含めないようにURLは出さない
        raise SystemExit(f"Instagram API エラー {e.code}: {body}")


def post_story(image_url, token):
    me = _call("GET", f"{API}/me", {"fields": "user_id,username", "access_token": token})
    ig_id = me["user_id"]
    print(f"投稿先: @{me.get('username')}")
    container = _call("POST", f"{API}/{ig_id}/media",
                      {"image_url": image_url, "media_type": "STORIES", "access_token": token})
    cid = container["id"]
    for _ in range(10):  # 公式推奨: 1分おき・最大5分程度の確認
        st = _call("GET", f"{API}/{cid}", {"fields": "status_code", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise SystemExit(f"画像の取り込みに失敗: {st}")
        time.sleep(30)
    res = _call("POST", f"{API}/{ig_id}/media_publish", {"creation_id": cid, "access_token": token})
    print(f"投稿完了 media_id={res.get('id')}")


def wait_until_post_time(cfg):
    if os.environ.get("SKIP_WAIT"):
        return
    hh, mm = map(int, cfg.get("post_time_jst", "11:00").split(":"))
    now = dt.datetime.now(JST)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if 0 < wait < 3600:
        print(f"{cfg.get('post_time_jst')} まで {int(wait)} 秒待機")
        time.sleep(wait)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    cfg = load_config()
    today = dt.datetime.now(JST).date()

    if cmd == "render":
        day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else today
        out, photo, layout = render(day, cfg)
        print(f"{day} {WEEKDAYS[day.weekday()]}: {photo} / レイアウト{layout}({LAYOUTS[layout][0]}) -> {out}")

    elif cmd == "prepare":  # GitHub Actions 用: 画像を作って公開の準備
        reason = is_closed(today, cfg)
        if reason and not os.environ.get("FORCE"):
            print(f"本日は{reason}のため投稿しません")
            Path(os.environ.get("GITHUB_OUTPUT", os.devnull)).open("a").write("skip=true\n")
            return
        out, photo, layout = render(today, cfg)
        cleanup(cfg, today)
        print(f"作成: {out.name}（{photo} / レイアウト{layout}）")
        Path(os.environ.get("GITHUB_OUTPUT", os.devnull)).open("a").write(f"skip=false\nimage={out.name}\n")

    elif cmd == "post":
        token = os.environ["IG_ACCESS_TOKEN"]
        base = os.environ["IMAGE_BASE_URL"].rstrip("/")
        name = sys.argv[2] if len(sys.argv) > 2 else f"{today.strftime('%Y%m%d')}.jpg"
        wait_until_post_time(cfg)
        post_story(f"{base}/{name}", token)

    elif cmd == "refresh":
        token = os.environ["IG_ACCESS_TOKEN"]
        res = _call("GET", "https://graph.instagram.com/refresh_access_token",
                    {"grant_type": "ig_refresh_token", "access_token": token})
        Path(os.environ.get("NEW_TOKEN_FILE", "new_token.txt")).write_text(res["access_token"])
        print(f"トークン更新完了（有効期間 {int(res.get('expires_in', 0)) // 86400} 日）")

    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
