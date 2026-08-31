# -*- coding: utf-8 -*-
"""云端主入口：拉取彩票（AGG/FENG）+ 银行，合并历史快照，输出 snapshot.json

凭证（环境变量，由 GitHub Actions Secrets 注入）：
    LOTTERY_PASS_AGG / LOTTERY_PASS_FENG   （各彩票点密码）
    GMAIL_USER / GMAIL_APP_PASS            （银行对账单，可选）

用法：
    python main.py [--date=YYYY-MM-DD]
"""
import os
import sys
import json
import datetime

from lottery_fetch import fetch_day
from snapshot_build import build_snapshot, save_snapshot


def today_local():
    """哥斯达黎加日期。workflow 已设 TZ=America/Costa_Rica，此处兜底 UTC-6。"""
    try:
        return datetime.datetime.now().date().isoformat()
    except Exception:
        pass
    now = datetime.datetime.utcnow() - datetime.timedelta(hours=6)
    return now.date().isoformat()


def load_prev(path="snapshot.json"):
    empty = {"main": [], "detail": [], "daily": [], "bank": []}
    if not os.path.exists(path):
        return empty
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k in empty:
            data.setdefault(k, [])
        return data
    except Exception:
        return empty


def main():
    date_str = today_local()
    for a in sys.argv[1:]:
        if a.startswith("--date="):
            date_str = a.split("=", 1)[1]

    prev = load_prev()

    accounts = {}
    for acc in ("AGG", "FENG"):
        user = os.environ.get(f"LOTTERY_USER_{acc}", acc)
        pw = os.environ.get(f"LOTTERY_PASS_{acc}", "") or os.environ.get("LOTTERY_PASS", "")
        if not pw:
            print(f"[skip] {acc}: 未配置密码", file=sys.stderr)
            continue
        try:
            rows = fetch_day(user, pw, date_str)
            if isinstance(rows, list) and rows:
                accounts[acc] = rows
                print(f"[ok] {acc}: {len(rows)} 场", file=sys.stderr)
            else:
                print(f"[warn] {acc}: 无数据 {rows}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {acc} 拉取失败: {exc}", file=sys.stderr)

    if not accounts:
        print(json.dumps({"error": "两个彩票账号均拉取失败"}, ensure_ascii=False))
        sys.exit(2)

    snap = build_snapshot(date_str, accounts, prev)
    save_snapshot(snap, "snapshot.json")
    print(json.dumps({
        "date": date_str,
        "accounts": list(accounts.keys()),
        "main": len(snap["main"]),
        "detail": len(snap["detail"]),
        "daily": len(snap["daily"]),
        "snapshotAt": snap["snapshotAt"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
