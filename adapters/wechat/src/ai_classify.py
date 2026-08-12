# -*- coding: utf-8 -*-
"""H3 L2 AI 精筛：对 L1 候选信号做语义判断 + 结构化抽取。

- 调用 OpenAI 兼容 Chat Completions API（DeepSeek / OpenAI / 本地网关均可）；
- 图片信号（form=B）走多模态：本地解密 jpg → base64 → 图片+上下文一起送；
- 配置读取项目根目录 .env.local（untracked）：
    WECHAT_AI_BASE_URL=https://api.deepseek.com/v1
    WECHAT_AI_API_KEY=sk-xxx
    WECHAT_AI_MODEL=deepseek-chat
- 未配置密钥时自动跳过（status=skipped），不阻断管道；
- 输出 JSON 写入 wechat_signal（confirmed/rejected + category/device/price/intent/summary）。

Usage:
  python ai_classify.py --staging <staging.sqlite> [--limit 50] [--dry-run]
  python ai_classify.py --staging <staging.sqlite> --images   # 仅重跑图片信号（多模态）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPT = """你是【游戏游艺设施设备】行业情报分析助手。判断给定微信消息是否与游戏游艺设施设备商品相关。

【属于】：
- 整机设备：娃娃机/抓物机/推币机/街机/彩票机/礼品机/扭蛋机/盲盒机/投篮机/赛车机/卡丁车/旋转木马/碰碰车/充气城堡/淘气堡/存票机/售币机/兑币机/音乐机/跳舞机/捕鱼机/射击机/摇摇车等
- 配件与耗材：扫码支付盒子/彩票器/礼品/公仔/卡片/游戏币/套件/主板/按键/屏幕等游艺设备专用配件
- 商品形态：出售/转让/清库存/二手/翻新/求购/货源/批发/租赁/回收，含价格数量新旧等
- 设备相关服务：文审、安装、维修、软件系统（电玩城管理/支付系统）

【不属于】（一律 is_product=false）：
- 招聘/贷款/记账报税/办证服务/餐饮/酒水(茅台等)/化妆品/服装/保险理财/房产/旅游/演绎演出/广告平台/通用电子(手机电脑)/日常闲聊/与游艺设备无关的一切

消息内容：
{content}

只输出 JSON，不要其他文字，格式：
{{"is_product": true或false, "category": "A01~E开头的分类码或空", "device": "设备名称或空", "price": 数字或null, "price_unit": "元/万/空", "intent": "sell|buy|info|unknown", "summary": "30字内中文摘要"}}"""

IMAGE_PROMPT = """你是【游戏游艺设施设备】行业情报分析助手。根据图片及上下文判断是否与游戏游艺设施设备商品相关。

【属于】：
- 整机设备：娃娃机/抓物机/推币机/街机/彩票机/礼品机/扭蛋机/盲盒机/投篮机/赛车机/卡丁车/旋转木马/碰碰车/充气城堡/淘气堡/存票机/售币机/兑币机/音乐机/跳舞机/捕鱼机/射击机/摇摇车等
- 配件与耗材：扫码支付盒子/彩票器/礼品/公仔/卡片/游戏币/套件/主板/按键/屏幕等游艺设备专用配件
- 商品形态：出售/转让/清库存/二手/翻新/求购/货源/批发/租赁/回收，含价格数量新旧等
- 设备相关服务：文审、安装、维修、软件系统（电玩城管理/支付系统）

【不属于】（一律 is_product=false）：
- 招聘/贷款/记账报税/办证服务/餐饮/酒水(茅台等)/化妆品/服装/保险理财/房产/旅游/演绎演出/广告平台/通用电子(手机电脑)/日常闲聊/与游艺设备无关的一切
- 纯人物/风景/表情包/截图等不含游艺设备的图片

从图片中提取尽可能多的结构化信息（图片中可能有参数、价格、规格、名称、多台实机等）。
只输出 JSON，不要其他文字，格式：
{"is_product": true或false, "category": "A01~E开头的分类码或空", "device": "设备名称或空", "price": 数字或null, "price_unit": "元/万/空", "intent": "sell|buy|info|unknown", "count": 数量或null, "summary": "30字内中文摘要"}"""


def _load_env():
    """读项目根 .env.local（KEY=VALUE，忽略空行/# 注释）。"""
    env = {}
    for base in (os.getcwd(), os.path.dirname(os.path.dirname(os.path.dirname(__file__)))):
        p = os.path.join(base, ".env.local")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    env[k.strip().lstrip("\ufeff")] = v.strip().strip('"').strip("'")
            break
    return env


class AIClassifier:
    def __init__(self, staging: str, env: dict = None):
        self.con = sqlite3.connect(staging)
        self.env = env if env is not None else _load_env()
        self.base_url = self.env.get("WECHAT_AI_BASE_URL", "").rstrip("/")
        self.api_key = self.env.get("WECHAT_AI_API_KEY", "")
        self.model = self.env.get("WECHAT_AI_MODEL", "deepseek-chat")
        self.available = bool(self.base_url and self.api_key)

    def close(self):
        self.con.close()

    def _call(self, content: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是严谨的结构化信息抽取助手。"},
                {"role": "user", "content": PROMPT.format(content=content)},
            ],
            "temperature": 0,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data["choices"][0]["message"]["content"])

    def _call_image(self, content: str, image_path: str) -> dict:
        """多模态调用：文字上下文 + 本地图片（base64 data URI）。"""
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        ext = os.path.splitext(image_path)[1].lstrip(".").lower() or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是严谨的结构化信息抽取助手。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": IMAGE_PROMPT + "\n\n上下文：\n" + content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{ext};base64,{b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data["choices"][0]["message"]["content"])

    def requeue_images(self) -> int:
        """把有图可识别的历史 rejected 图片信号置回 pending（一次性重跑）。"""
        cur = self.con.execute(
            "UPDATE wechat_signal SET status='pending' WHERE id IN ("
            "SELECT s.id FROM wechat_signal s "
            "JOIN wechat_img i ON i.chat = s.chat_name "
            "AND i.local_id = CAST(substr(s.source_key, "
            "instr(s.source_key, ':') + 1) AS INTEGER) "
            "WHERE s.form='B' AND s.status='rejected' "
            "AND i.jpg_path IS NOT NULL AND i.dec_ok=1)"
        )
        self.con.commit()
        return cur.rowcount

    def run(
        self,
        limit: int = 50,
        dry_run: bool = False,
        workers: int = 5,
        images: bool = False,
    ) -> dict:
        if not self.available:
            # 无配置：全部 pending 标记 skipped（幂等）
            self.con.execute(
                "UPDATE wechat_signal SET status='skipped' WHERE status='pending'"
            )
            self.con.commit()
            return {"mode": "skipped_no_api_key", "count": 0}
        if images:
            # 图片信号：pending/error（处理后不再重复选中）
            rows = self.con.execute(
                "SELECT s.id, s.chat_name, s.sender, s.create_time, s.text, s.hits, "
                "i.jpg_path FROM wechat_signal s "
                "LEFT JOIN wechat_img i ON i.chat = s.chat_name "
                "AND i.local_id = CAST(substr(s.source_key, "
                "instr(s.source_key, ':') + 1) AS INTEGER) "
                "WHERE s.form='B' AND s.status IN ('pending','error') "
                "AND i.jpg_path IS NOT NULL AND i.dec_ok=1 "
                "ORDER BY s.group_weight DESC, s.create_time LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self.con.execute(
                "SELECT id, chat_name, sender, create_time, text, hits, NULL "
                "FROM wechat_signal WHERE status='pending' "
                "ORDER BY group_weight DESC, create_time LIMIT ?",
                (limit,),
            ).fetchall()
        if dry_run:
            for sid, chat, sender, ctime, text, hits, img in rows:
                if img:
                    print(f"[dry] #{sid} [IMG] {img}\n  {chat} {ctime} {str(text)[:100]}")
                else:
                    print(f"[dry] #{sid}: {chat} {ctime} {str(text)[:120]}")
            return {"mode": "dry_run", "count": len(rows)}

        def work(row):
            sid, chat, sender, ctime, text, hits, img = row
            content = (
                f"群/来源: {chat}\n发送者: {sender}\n时间: {ctime}\n"
                f"预筛命中: {hits}\n消息内容: {text}"
            )
            try:
                result = self._call_image(content, img) if img else self._call(content)
                is_product = bool(result.get("is_product"))
                return (
                    sid,
                    "confirmed" if is_product else "rejected",
                    str(result.get("category") or ""),
                    str(result.get("device") or ""),
                    result.get("price"),
                    str(result.get("intent") or "unknown"),
                    str(result.get("summary") or ""),
                    json.dumps(result, ensure_ascii=False),
                )
            except Exception as exc:  # noqa: BLE001
                return (
                    sid,
                    "error",
                    "",
                    "",
                    None,
                    "unknown",
                    "",
                    f"ERR: {exc}"[:500],
                )

        ok = err = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for sid, status, cat, dev, price, intent, summary, ai_raw in pool.map(
                work, rows
            ):
                self.con.execute(
                    "UPDATE wechat_signal SET status=?, category=?, device=?, price=?, "
                    "intent=?, summary=?, ai_raw=? WHERE id=?",
                    (status, cat, dev, price, intent, summary, ai_raw, sid),
                )
                if status == "error":
                    err += 1
                else:
                    ok += 1
        self.con.commit()
        return {
            "mode": "api",
            "processed": ok + err,
            "ok": ok,
            "error": err,
            "workers": workers,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", required=True)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--images", action="store_true", help="仅重跑图片信号（多模态）")
    ap.add_argument("--requeue-images", action="store_true", help="历史 rejected 图片信号置回 pending")
    args = ap.parse_args()
    clf = AIClassifier(args.staging)
    if args.requeue_images:
        n = clf.requeue_images()
        print(json.dumps({"requeued": n}, ensure_ascii=False))
    else:
        print(json.dumps(clf.run(args.limit, args.dry_run, args.workers, args.images), ensure_ascii=False))
    clf.close()


if __name__ == "__main__":
    main()
