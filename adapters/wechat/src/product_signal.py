# -*- coding: utf-8 -*-
"""H3 L1 商品信号预筛：把微信消息/朋友圈过滤为商品候选信号。

规则（成本≈0，秒级）：
  1. 链接信号：电商域名白名单（淘宝/京东/拼多多/1688/闲鱼/抖音/快手/有赞…）
  2. 设备词信号：product_keywords.json（来自项目分类清单，763 词，分强/弱）
  3. 报价信号：¥/￥/元/块/万/w/k + 数字
  4. 图片信号：图片消息可能含商品图（留给 AI/OCR）
  5. 群权重（config/group_weights.json）：S=3/A=2/B=1/C=0 加权 score
  6. 形态分拣：form = A纯文字 | B图片 | C链接 | D混合

输出：写 staging.wechat_signal（status=pending），由 L2 AI 精筛消费。

Usage:
  python signal.py --staging <staging.sqlite>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from typing import Dict, List, Optional

DDL = """
CREATE TABLE IF NOT EXISTS wechat_signal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,          -- msg | moment
  source_key TEXT NOT NULL UNIQUE,    -- msg: <chat>:<local_id>; moment: <moment_id>
  form TEXT,                          -- A|B|C|D 信息形态
  group_weight INTEGER,               -- 来源群权重 3/2/1/0
  chat_name TEXT,
  chat_display TEXT,
  sender TEXT,
  create_time INTEGER,
  text TEXT,
  hits TEXT,                          -- JSON: 命中信号明细
  score REAL,
  status TEXT DEFAULT 'pending',      -- pending | confirmed | rejected | skipped | error
  category TEXT,
  device TEXT,
  price REAL,
  intent TEXT,                        -- sell | buy | info | unknown
  summary TEXT,
  ai_raw TEXT,
  created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_signal_status ON wechat_signal(status);
CREATE INDEX IF NOT EXISTS idx_signal_time ON wechat_signal(create_time);
"""

# 电商域名白名单（含短链域）
ECOMMERCE_DOMAINS = {
    "taobao.com", "tmall.com", "tb.cn",
    "jd.com", "3.cn",
    "pinduoduo.com", "yangkeduo.com", "pdd.com", "mobile.yangkeduo.com",
    "1688.com",
    "goofish.com", "xianyu",
    "douyin.com", "iesdouyin.com",
    "kuaishou.com", "gifshow.com",
    "weidian.com", "weidianyige.com",
    "youzan.com", "koudaitong.com",
    "meituan.com", "ele.me", "dianping.com",
    "suning.com", "gome.com.cn", "vip.com", "yohobuy.com", "dangdang.com",
}

URL_RE = re.compile(r"https?://([^\s\"'<>，。；：]+)", re.IGNORECASE)
PRICE_RE = re.compile(
    r"([¥￥]\s*[0-9][0-9,.]*|"
    r"[0-9][0-9,.]*\s*(?:元|块|万|w|W|k)|"
    r"[0-9][0-9,.]*\s*[-~到至]\s*[0-9][0-9,.]*\s*(?:元|块|万|w|W))"
)

WEIGHT_MULT = {3: 1.5, 2: 1.2, 1: 1.0, 0: 0.5}

# 硬排除：命中且无游艺设备强词 → 直接不进候选（省 AI 成本）
IRRELEVANT_TERMS = [
    "招聘", "诚聘", "诚招", "招人", "面试", "岗位", "工资", "保底", "日结",
    "贷款", "借款", "抵押", "保单", "公积金", "车贷", "房贷", "信用卡",
    "记账", "报税", "工商年报", "财税",
    "茅台", "白酒", "红酒", "烟", "雪茄", "茶叶", "食品", "零食", "水果",
    "化妆品", "假睫毛", "护肤品", "面膜", "美甲", "服装", "女装", "男装",
    "保险", "理财", "基金", "股票", "投资",
    "旅游", "机票", "酒店", "餐饮", "外卖", "火锅",
    "房产", "租房", "买房", "楼盘", "中介",
    "演绎", "演出", "主持", "礼仪", "模特", "舞蹈队",
    "广告位", "广告平台", "户外广告", "推广平台",
    "汽车", "二手车", "新能源车", "加油",
    "手机", "平板", "电脑", "耳机", "手表", "家电", "空调", "冰箱",
]


def load_keywords(path: str) -> Dict[str, List[dict]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    strong, weak = [], []
    for item in data["keywords"]:
        kw = item["keyword"]
        # 2 字通用词视为弱信号，其余为强信号
        (weak if len(kw) <= 2 else strong).append(item)
    return {"strong": strong, "weak": weak}


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return ""
    host = m.group(1).lower()
    host = re.sub(r"^www\.", "", host)
    for d in ECOMMERCE_DOMAINS:
        if host == d or host.endswith("." + d):
            return d
    return ""


def detect_form(text: str, type_name: str) -> str:
    """形态分拣：A纯文字 | B图片 | C链接 | D混合。"""
    has_url = bool(URL_RE.search(text or ""))
    is_img = type_name == "image"
    if has_url and is_img:
        return "D"
    if has_url:
        return "C"
    if is_img:
        return "B"
    return "A"


class SignalDetector:
    def __init__(self, staging: str, keywords_path: str):
        self.con = sqlite3.connect(staging)
        self.con.executescript(DDL)
        self._migrate()
        self.kw = load_keywords(keywords_path)
        self.group_weights = self._load_group_weights()

    def _migrate(self):
        cols = [r[1] for r in self.con.execute("PRAGMA table_info(wechat_signal)")]
        for col, ddl in (("form", "TEXT"), ("group_weight", "INTEGER")):
            if col not in cols:
                self.con.execute(f"ALTER TABLE wechat_signal ADD COLUMN {col} {ddl}")

    def _load_group_weights(self) -> dict:
        path = os.path.join(
            os.path.dirname(__file__), "..", "config", "group_weights.json"
        )
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {g["chat"]: g["weight"] for g in data.get("groups", [])}

    def _weight_of(self, chat: str) -> int:
        return self.group_weights.get(chat, 1)

    def close(self):
        self.con.close()

    def _analyze(self, text: str, is_image: bool) -> tuple:
        # 乱码过滤：不可打印字符占比过高视为二进制乱码，不产生信号
        if text:
            printable = sum(
                1 for ch in text if (ch.isprintable() and ch != "\ufffd") or ch == "\n"
            )
            if printable / len(text) < 0.7:
                return [], 0.0
        hits = []
        score = 0.0
        # 硬排除：无关词命中且无强设备词 → 直接返回空
        strong_hits = [
            item
            for item in self.kw["strong"]
            if item["keyword"] in (text or "")
        ]
        if any(t in (text or "") for t in IRRELEVANT_TERMS) and not strong_hits:
            return [], 0.0
        # 1) 链接
        for m in URL_RE.finditer(text or ""):
            url = m.group(0)
            dom = _domain_of(url)
            if dom:
                hits.append({"type": "link", "domain": dom, "url": url[:200]})
                score += 2.0
        # 2) 设备词
        for item in strong_hits:
            if item["keyword"] in (text or ""):
                hits.append(
                    {
                        "type": "keyword",
                        "kw": item["keyword"],
                        "category": item["category"],
                        "strength": "strong",
                    }
                )
                score += 2.0
        weak_hits = 0
        for item in self.kw["weak"]:
            if item["keyword"] in (text or ""):
                weak_hits += 1
                if weak_hits <= 3:
                    hits.append(
                        {
                            "type": "keyword",
                            "kw": item["keyword"],
                            "category": item["category"],
                            "strength": "weak",
                        }
                    )
        score += 0.5 * weak_hits
        # 3) 报价
        prices = PRICE_RE.findall(text or "")
        if prices:
            hits.append({"type": "price", "matches": prices[:5]})
            score += 1.0
        # 4) 图片
        if is_image:
            hits.append({"type": "image"})
            score += 1.0
        return hits, round(score, 2)

    def scan_new(self) -> dict:
        """扫描新消息/朋友圈 → wechat_signal（幂等：source_key UNIQUE）。"""
        now = int(time.time())
        inserted = 0
        # 消息（仅文本与图片类型，其余类型暂不预筛）
        rows = self.con.execute(
            "SELECT chat_name, local_id, create_time, sender_id, type_name, text "
            "FROM wechat_msg WHERE type_name IN ('text','image') "
            "ORDER BY create_time"
        ).fetchall()
        for chat, local_id, ctime, sender, typ, text in rows:
            key = f"{chat}:{local_id}"
            exists = self.con.execute(
                "SELECT 1 FROM wechat_signal WHERE source_key=?", (key,)
            ).fetchone()
            if exists:
                continue
            hits, score = self._analyze(text or "", typ == "image")
            w = self._weight_of(chat)
            # 图片消息：仅 S/A 级群进入候选（避免闲聊群表情包洪水），交由 AI/OCR 判断
            if typ == "image" and w < 2:
                continue
            if score >= 1.0:
                form = detect_form(text or "", typ)
                self.con.execute(
                    "INSERT OR IGNORE INTO wechat_signal "
                    "(source_type, source_key, form, group_weight, chat_name, sender, "
                    "create_time, text, hits, score, created_at) "
                    "VALUES ('msg',?,?,?,?,?,?,?,?,?,?)",
                    (
                        key, form, w, chat, str(sender), ctime,
                        (text or "")[:2000], json.dumps(hits, ensure_ascii=False),
                        round(score * WEIGHT_MULT.get(w, 1.0), 2), now,
                    ),
                )
                inserted += 1
        # 朋友圈
        mrows = self.con.execute(
            "SELECT moment_id, user_name, create_time, content_desc FROM wechat_moment "
            "ORDER BY create_time"
        ).fetchall()
        for mid, user, ctime, desc in mrows:
            key = f"moment:{mid}"
            exists = self.con.execute(
                "SELECT 1 FROM wechat_signal WHERE source_key=?", (key,)
            ).fetchone()
            if exists:
                continue
            hits, score = self._analyze(desc or "", False)
            if score >= 1.0:
                w = self._weight_of(chat) if chat else 1
                form = detect_form(desc or "", "text")
                self.con.execute(
                    "INSERT OR IGNORE INTO wechat_signal "
                    "(source_type, source_key, form, group_weight, chat_name, sender, "
                    "create_time, text, hits, score, created_at) "
                    "VALUES ('moment',?,?,?,?,?,?,?,?,?,?)",
                    (key, form, w, user, user, ctime, (desc or "")[:2000],
                     json.dumps(hits, ensure_ascii=False),
                     round(score * WEIGHT_MULT.get(w, 1.0), 2), now),
                )
                inserted += 1
        self.con.commit()
        return {"inserted": inserted, "pending": self._pending_count()}

    def _pending_count(self) -> int:
        return self.con.execute(
            "SELECT COUNT(*) FROM wechat_signal WHERE status='pending'"
        ).fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    ap.add_argument(
        "--keywords",
        default=os.path.join(
            os.path.dirname(__file__), "..", "config", "product_keywords.json"
        ),
    )
    args = ap.parse_args()
    det = SignalDetector(args.staging, args.keywords)
    print(json.dumps(det.scan_new(), ensure_ascii=False))
    det.close()


if __name__ == "__main__":
    main()
