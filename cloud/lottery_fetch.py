# -*- coding: utf-8 -*-
"""彩票后台数据拉取脚本（云端版）

登录 dashboardtimes.com/LuckyStar，拉取指定日期（默认今天）的按场次报表。

凭证从环境变量读取（GitHub Actions Secrets 注入）：
    LOTTERY_USER / LOTTERY_PASS

用法：
    python lottery_fetch.py [YYYY-MM-DD] [--user XXX] [--password XXX]

输出：stdout 打印 JSON 数组，每条记录：
    {evento, fecha_sorteo, hora, tipo, importe, jugadas, comision, premio,
     ahorro, prestamo, balance, descripcion, fecha_transaccion}
金额已转为 float，¢ 与千分位逗号已去除。
"""
import os
import re
import sys
import json
import datetime

from playwright.sync_api import sync_playwright

BASE_URL = "https://dashboardtimes.com/LuckyStar"

JS_EXTRACT = """
() => {
  const tables = Array.from(document.querySelectorAll('table'));
  const t = tables.find(tb => (tb.innerText || '').includes('Evento'));
  if (!t) return null;
  const rows = Array.from(t.querySelectorAll('tbody tr, tr'));
  const out = [];
  for (const r of rows) {
    const cells = Array.from(r.querySelectorAll('td'));
    if (cells.length < 10) continue;
    const txt = (c) => (c.innerText || '').trim();
    out.push({
      evento: txt(cells[0]),
      fecha_sorteo: txt(cells[1]),
      tipo: txt(cells[2]),
      importe: txt(cells[3]),
      jugadas: txt(cells[4]),
      comision: txt(cells[5]),
      premio: txt(cells[6]),
      ahorro: txt(cells[7]),
      prestamo: txt(cells[8]),
      balance: txt(cells[9]),
      descripcion: txt(cells[10]),
      fecha_transaccion: txt(cells[11])
    });
  }
  return out;
}
"""


def to_float(s):
    """哥斯达黎加金额格式：点为千分位、逗号为小数点。如 ¢2.050 -> 2050.0。"""
    if s is None:
        return 0.0
    s = str(s).strip().replace("\u00a2", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return 0.0
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


def parse_record(rec, date_str):
    """把页面原始行解析为干净结构。"""
    fs = (rec.get("fecha_sorteo") or "").strip()
    hora = ""
    if " " in fs:
        hora = fs.split(" ")[1][:5] if len(fs.split(" ")) > 1 else ""
    return {
        "evento": (rec.get("evento") or "").strip(),
        "fecha": date_str,
        "fecha_sorteo": fs,
        "hora": hora,
        "importe": to_float(rec.get("importe")),
        "comision": to_float(rec.get("comision")),
        "premio": to_float(rec.get("premio")),
        "balance": to_float(rec.get("balance")),
        "tipo": (rec.get("tipo") or "").strip(),
    }


def fetch_day(user, password, date_str, timeout_ms=60000):
    """拉取指定日期报表，返回解析后的记录列表。"""
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        try:
            # 1. 登录
            page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=timeout_ms)
            page.fill("#txtUsuario", user)
            page.fill("#txtContrasena", password)
            page.click("#btnLogin")
            page.wait_for_selector("text=Bienvenido", timeout=timeout_ms)
            # 2. 打开报表页
            page.goto(f"{BASE_URL}/reporteordsorteo", wait_until="domcontentloaded", timeout=timeout_ms)
            # 3. 填日期并提交（Pickadate 只读输入框，用原生 setter 写入）
            page.evaluate(
                """(d) => {
                    const setV = (id) => {
                        const el = document.getElementById(id);
                        if (!el) return;
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(el, d);
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    };
                    setV('txtFechaInicio');
                    setV('txtFechaFin');
                }""",
                date_str,
            )
            page.click("button:has-text('Ver')")
            # 4. 轮询等待结果表出现（无数据时表头也会出现，最多等 ~30s）
            table_ok = False
            for _ in range(15):
                page.wait_for_timeout(2000)
                try:
                    table_ok = page.evaluate(
                        """() => Array.from(document.querySelectorAll('table'))
                            .some(t => (t.innerText||'').includes('Evento'))"""
                    )
                except Exception:
                    table_ok = False
                if table_ok:
                    break
            if not table_ok:
                return []
            raw = page.evaluate(JS_EXTRACT) or []
            for r in raw:
                rec = parse_record(r, date_str)
                if rec["evento"]:
                    results.append(rec)
        finally:
            browser.close()
    return results


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    date_str = args[0] if args else datetime.date.today().isoformat()
    user = os.environ.get("LOTTERY_USER", "AGG")
    password = os.environ.get("LOTTERY_PASS", "")
    if not password:
        print(json.dumps({"error": "缺少凭证 LOTTERY_PASS"}, ensure_ascii=False))
        sys.exit(1)
    try:
        rows = fetch_day(user, password, date_str)
        print(json.dumps(rows, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)[:500]}, ensure_ascii=False))
        sys.exit(2)


if __name__ == "__main__":
    main()
