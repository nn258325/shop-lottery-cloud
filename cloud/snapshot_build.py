# -*- coding: utf-8 -*-
"""快照组装：彩票报表行 -> SNAPSHOT JSON 结构

SNAPSHOT 结构（与工作台网页版一致）：
{
  "main":  [ {日期, 主体, 类别(销售/兑奖), 账面金额, 实盘金额, 差异, 状态, 备注, ...} ],
  "detail":[ {日期, 彩票点, 场次, 开奖时间, 投注金额, 佣金, 兑奖金额, 余额, 兑奖状态, 兑奖单号} ],
  "daily": [ {日期, 彩票点, 投注金额, 佣金, 兑奖金额, 余额, 场次数, 更新时间} ],
  "bank":  [ {月份, 刷卡总额, 到账总额, 被扣金额, 手续费, 更新时间} ],
  "snapshotAt": "YYYY-MM-DD HH:MM"
}

与历史快照合并策略（云端脚本维护全量文件）：
- 当天彩票相关记录（detail 场次明细 / daily 汇总 / main 中彩票点销售+兑奖）整体替换
- 其他记录（杂货记账、其他日期、bank）原样保留
- 主键：detail/daily 用 "{彩票点}-{日期}-{场次}" 风格的稳定 _id
"""
import json
import datetime

POINT_NAMES = {"AGG": "彩票点1", "FENG": "彩票点2"}


def _now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _uid(prefix, *parts):
    s = "-".join(str(x) for x in parts if x)
    return f"{prefix}-{s}"


def build_snapshot(date_str, points_rows, prev=None, bank_rows=None):
    """points_rows: {"AGG": [row...], "FENG": [row...]}"""
    prev = prev or {"main": [], "detail": [], "daily": [], "bank": []}
    main_out, detail_out, daily_out = [], [], []
    cloud_ids = set()

    for acc, rows in points_rows.items():
        point = POINT_NAMES.get(acc, acc)
        total_bet = 0.0
        total_com = 0.0
        total_premio = 0.0
        total_balance = 0.0
        for r in rows:
            evento = r["evento"]
            det_id = _uid("cd", point, date_str, evento)
            cloud_ids.add(det_id)
            estado = "待兑奖" if r["premio"] > 0 else "已兑奖"
            detail_out.append({
                "_id": det_id,
                "日期": date_str,
                "彩票点": point,
                "场次": evento,
                "开奖时间": r["hora"],
                "投注金额": r["importe"],
                "佣金": r["comision"],
                "兑奖金额": r["premio"],
                "余额": r["balance"],
                "兑奖状态": estado,
                "兑奖单号": "",
            })
            total_bet += r["importe"]
            total_com += r["comision"]
            total_premio += r["premio"]
            total_balance += r["balance"]
            # 主表：销售记录（已核对）
            sid = _uid("cs", point, date_str, evento)
            cloud_ids.add(sid)
            main_out.append({
                "_id": sid,
                "日期": date_str,
                "主体": point,
                "类别": "销售",
                "账面金额": r["importe"],
                "实盘金额": r["importe"],
                "差异": 0,
                "状态": "已核对",
                "备注": f"{evento} {r['hora']}",
                "彩票号": "",
                "兑奖单号": "",
                "支出类型": "",
                "收入类型": "",
            })
            # 主表：兑奖记录（待核对）
            if r["premio"] > 0:
                cid = _uid("cw", point, date_str, evento)
                cloud_ids.add(cid)
                main_out.append({
                    "_id": cid,
                    "日期": date_str,
                    "主体": point,
                    "类别": "兑奖",
                    "账面金额": r["premio"],
                    "实盘金额": 0,
                    "差异": 0,
                    "状态": "待核对",
                    "备注": f"{evento} 平台结算待兑",
                    "彩票号": "",
                    "兑奖单号": "",
                    "支出类型": "",
                    "收入类型": "",
                })
        # 日报汇总
        did = _uid("cdd", point, date_str)
        cloud_ids.add(did)
        daily_out.append({
            "_id": did,
            "日期": date_str,
            "彩票点": point,
            "投注金额": round(total_bet, 2),
            "佣金": round(total_com, 2),
            "兑奖金额": round(total_premio, 2),
            "余额": round(total_balance, 2),
            "场次数": len(rows),
            "更新时间": _now_str(),
        })

    # 合并历史：仅对本次成功拉取的彩票点做「当天整体替换」，其余保留
    active_points = set(POINT_NAMES.get(a, a) for a in points_rows.keys())

    def is_lot_main(m):
        return (m.get("日期") == date_str
                and m.get("主体") in ("彩票点1", "彩票点2")
                and m.get("主体") in active_points)

    def is_lot_detail(d):
        return (d.get("日期") == date_str
                and d.get("彩票点") in ("彩票点1", "彩票点2")
                and d.get("彩票点") in active_points)

    def is_lot_daily(d):
        return (d.get("日期") == date_str
                and d.get("彩票点") in ("彩票点1", "彩票点2")
                and d.get("彩票点") in active_points)

    main_keep = [m for m in prev.get("main", [])
                 if not (m.get("日期") == date_str and is_lot_main(m))]
    detail_keep = [d for d in prev.get("detail", [])
                   if not (d.get("日期") == date_str and is_lot_detail(d))]
    daily_keep = [d for d in prev.get("daily", [])
                  if not (d.get("日期") == date_str and is_lot_daily(d))]

    main_all = main_keep + main_out
    detail_all = detail_keep + detail_out
    daily_all = daily_keep + daily_out

    # 按日期排序
    def by_date(item):
        return item.get("日期", "")

    main_all.sort(key=by_date)
    detail_all.sort(key=by_date)
    daily_all.sort(key=by_date)

    bank_all = prev.get("bank", []) if not bank_rows else bank_rows

    return {
        "main": main_all,
        "detail": detail_all,
        "daily": daily_all,
        "bank": bank_all,
        "snapshotAt": _now_str(),
    }


def save_snapshot(snapshot, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
    return path
