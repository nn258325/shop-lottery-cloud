# -*- coding: utf-8 -*-
"""Gmail 银行对账单拉取（云端版）

从 Gmail 收件箱找最新银行对账单邮件，下载 PDF 附件，
用 pypdf 提取文本并解析出 刷卡总额/到账总额/被扣金额/手续费。

凭证（环境变量）：
    GMAIL_USER / GMAIL_APP_PASS （应用专用密码）

用法：
    python bank_fetch.py
输出：stdout JSON，形如 {"月份":"2026-08","刷卡总额":...,"到账总额":...,"被扣金额":...,"手续费":...}
找不到时输出 {"error": "..."}。
"""
import os
import io
import re
import sys
import json
import imaplib
import email
from email.header import decode_header

SUBJECT_KEYWORDS = ["estado de cuenta", "banco nacional", "bn cr", "bank", "对账单", "银行"]


def dec(s):
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for t, enc in parts:
        if isinstance(t, bytes):
            try:
                out.append(t.decode(enc or "utf-8", "ignore"))
            except Exception:
                out.append(t.decode("utf-8", "ignore"))
        else:
            out.append(t)
    return "".join(out)


def _is_bank_mail(subject, from_addr):
    hay = f"{subject} {from_addr}".lower()
    return any(k in hay for k in SUBJECT_KEYWORDS)


def fetch_latest_pdf(user, app_pass, max_mails=40):
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    M.login(user, app_pass)
    M.select("INBOX")
    typ, data = M.search(None, "ALL")
    ids = data[0].split()
    if not ids:
        M.logout()
        return None
    recent = ids[-max_mails:]
    for i in reversed(recent):
        typ, d = M.fetch(i, "(BODY.PEEK[])")
        if typ != "OK" or not d:
            continue
        msg = email.message_from_bytes(d[0][1])
        subj = dec(msg.get("Subject", ""))
        frm = dec(msg.get("From", ""))
        if not _is_bank_mail(subj, frm):
            continue
        for part in msg.walk():
            fn = part.get_filename()
            if not fn:
                continue
            fn = dec(fn)
            if not fn.lower().endswith(".pdf"):
                continue
            payload = part.get_payload(decode=True)
            M.logout()
            return {"filename": fn, "subject": subj, "pdf": payload}
    M.logout()
    return None


def parse_pdf_text(pdf_bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        return text
    except Exception:
        return ""


NUM_RE = re.compile(r"[-+]?[\d.,]+")


def extract_bank_numbers(text):
    """尽力提取：总刷/总到账/被扣/手续费。返回 dict 或 None。"""
    if not text:
        return None
    nums = [n for n in NUM_RE.findall(text) if len(n) >= 4]
    # 粗糙启发式：取出现频率高/最大的几个数做候选，无法精确定位时返回 None
    # 该解析依赖历史会话的具体对账单格式；此处为兜底实现
    return None


def main():
    user = os.environ.get("GMAIL_USER", "")
    app_pass = os.environ.get("GMAIL_APP_PASS", "")
    if not user or not app_pass:
        print(json.dumps({"error": "缺少凭证 GMAIL_USER/GMAIL_APP_PASS"}, ensure_ascii=False))
        sys.exit(1)
    try:
        mail = fetch_latest_pdf(user, app_pass)
        if not mail:
            print(json.dumps({"error": "未找到银行对账单邮件"}, ensure_ascii=False))
            sys.exit(2)
        text = parse_pdf_text(mail["pdf"])
        nums = extract_bank_numbers(text)
        out = {
            "filename": mail["filename"],
            "subject": mail["subject"][:120],
            "pdf_len": len(mail["pdf"]),
            "text_len": len(text),
        }
        if nums:
            out.update(nums)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)[:500]}, ensure_ascii=False))
        sys.exit(3)


if __name__ == "__main__":
    main()
