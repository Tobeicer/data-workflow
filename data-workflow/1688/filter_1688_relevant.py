from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

POSITIVE = re.compile(
    r"(娃娃机|抓娃娃|夹娃娃|投币|退币|出票|彩票机|兑币|游艺|街机|电玩|礼品机|扭蛋机|篮球机|捕鱼|框体|机箱|天车|爪子|爪片|按钮|按键|微动|摇杆|主板|电源|灯条|跑马灯|锁具|门锁|币斗|币道|马达|彩票|游戏币|游戏机配件)"
)

NEGATIVE = re.compile(
    r"(Switch|switch|SWITCH|PS5|PS4|PS3|XBOX|Xbox|xbox|ONE|任天堂|索尼|手柄|摇杆帽|保护壳|保护套|收纳包|蓝牙|耳机|吃鸡|手机|平板|掌机|3DS|NDS|PSP|PSV|键盘|鼠标|鼠标垫|数据线|充电线|高清线|HDMI|支架|散热|防尘|硅胶|钢化膜|游戏卡|卡带)"
)

STRONG_POSITIVE = re.compile(
    r"(娃娃机|抓娃娃|夹娃娃|投币|退币|出票|彩票机|兑币|游艺|街机|电玩|礼品机|扭蛋机|篮球机|捕鱼|框体|机箱|天车|爪子|爪片|按钮|按键|微动|跑马灯|锁具|门锁|币斗|游戏币)"
)


def is_relevant(keyword: str, title: str) -> bool:
    text = f"{keyword} {title}"
    if not POSITIVE.search(text):
        return False
    if NEGATIVE.search(text) and not STRONG_POSITIVE.search(text):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str).fillna("")
    keyword_col = "keyword" if "keyword" in df.columns else "source_keyword"
    title_col = "product_title"
    mask = [is_relevant(row.get(keyword_col, ""), row.get(title_col, "")) for _, row in df.iterrows()]
    filtered = df[mask].copy()
    filtered["relevance_filter_status"] = "kept"
    filtered["relevance_filter_note"] = "游艺圈相关关键词命中，且未命中消费电子强排除规则"

    output = Path(args.output) if args.output else BASE_DIR / f"1688_relevant_offer_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(output, index=False, encoding="utf-8-sig")

    print(f"input_rows={len(df)}")
    print(f"filtered_rows={len(filtered)}")
    print(f"output={output}")
    if keyword_col in filtered.columns:
        print("keyword_counts:")
        print(filtered.groupby(keyword_col).size().to_string())
    excluded_columns = [col for col in (keyword_col, title_col) if col in df.columns]
    if excluded_columns:
        print("excluded_sample:")
        print(df[~pd.Series(mask)][excluded_columns].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
