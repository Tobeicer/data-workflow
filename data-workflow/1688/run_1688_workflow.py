from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent


def run_command(command: list[str], *, dry_run: bool) -> None:
    print("[1688-workflow] " + " ".join(command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def add_repeated_option(command: list[str], option: str, values: list[str] | None) -> None:
    for value in values or []:
        command.extend([option, value])


def prepare_login(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(BASE_DIR / "collect_1688_public_sample.py"),
        "--prepare-login",
        "--login-wait-seconds",
        str(args.login_wait_seconds),
    ]
    run_command(command, dry_run=args.dry_run)


def sample(args: argparse.Namespace) -> None:
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else BASE_DIR / "runs" / stamp

    list_csv = output_dir / f"1688_offer_index_{stamp}.csv"
    relevant_csv = output_dir / f"1688_relevant_offer_index_{stamp}.csv"
    detail_csv = output_dir / f"1688_relevant_product_detail_{stamp}.csv"
    sku_csv = output_dir / f"1688_relevant_product_sku_{stamp}.csv"

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    list_command = [
        sys.executable,
        str(BASE_DIR / "collect_1688_public_sample.py"),
        "--output",
        str(list_csv),
        "--limit-per-keyword",
        str(args.limit_per_keyword),
        "--delay-seconds",
        str(args.delay_seconds),
        "--scroll-count",
        str(args.scroll_count),
    ]
    add_repeated_option(list_command, "--keyword", args.keyword)
    if args.debug:
        list_command.append("--debug")
    run_command(list_command, dry_run=args.dry_run)

    filter_command = [
        sys.executable,
        str(BASE_DIR / "filter_1688_relevant.py"),
        "--input",
        str(list_csv),
        "--output",
        str(relevant_csv),
    ]
    run_command(filter_command, dry_run=args.dry_run)

    if not args.skip_detail:
        detail_command = [
            sys.executable,
            str(BASE_DIR / "collect_1688_detail_sample.py"),
            "--input-csv",
            str(relevant_csv),
            "--start",
            str(args.detail_start),
            "--limit",
            str(args.detail_limit),
            "--delay-seconds",
            str(args.detail_delay_seconds),
            "--detail-output",
            str(detail_csv),
            "--sku-output",
            str(sku_csv),
        ]
        if args.debug:
            detail_command.append("--debug")
        run_command(detail_command, dry_run=args.dry_run)

    print("[1688-workflow] 输出目录：" + str(output_dir))
    print("[1688-workflow] 列表样本：" + str(list_csv))
    print("[1688-workflow] 相关商品：" + str(relevant_csv))
    if not args.skip_detail:
        print("[1688-workflow] 详情样本：" + str(detail_csv))
        print("[1688-workflow] SKU 样本：" + str(sku_csv))


def company(args: argparse.Namespace) -> None:
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else BASE_DIR.parent / "runtime" / "runs" / "1688" / f"1688_company_{stamp}"
    )
    collector = BASE_DIR.parent / "adapters" / "1688" / "src" / "collect_company_pilot.py"
    command = [
        sys.executable,
        str(collector),
        "--offer-id",
        args.offer_id,
        "--output-dir",
        str(output_dir),
        "--delay-seconds",
        str(args.delay_seconds),
    ]
    if args.profile_dir:
        command.extend(["--profile-dir", args.profile_dir])
    if args.debug:
        command.append("--debug")
    if args.headless:
        command.append("--headless")
    run_command(command, dry_run=args.dry_run)
    print("[1688-workflow] 公司试采输出目录：" + str(output_dir))


def multi(args: argparse.Namespace) -> None:
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else BASE_DIR.parent / "runtime" / "runs" / "1688" / f"1688_multi_{stamp}"
    )
    collector = BASE_DIR.parent / "adapters" / "1688" / "src" / "multi_product_workflow.py"
    command = [
        sys.executable,
        str(collector),
        "--input",
        args.input,
        "--output-dir",
        str(output_dir),
        "--delay-seconds",
        str(args.delay_seconds),
    ]
    if args.profile_dir:
        command.extend(["--profile-dir", args.profile_dir])
    if args.debug:
        command.append("--debug")
    if args.headless:
        command.append("--headless")
    run_command(command, dry_run=args.dry_run)
    print("[1688-workflow] 多商品批次输出目录：" + str(output_dir))


def main() -> None:
    parser = argparse.ArgumentParser(description="1688 补充性商品样本采集工作流入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("prepare-login", help="打开 1688 登录页并保存本地浏览器登录态")
    login_parser.add_argument("--login-wait-seconds", type=int, default=240)
    login_parser.add_argument("--dry-run", action="store_true")
    login_parser.set_defaults(func=prepare_login)

    sample_parser = subparsers.add_parser("sample", help="执行列表采样、相关性筛选和可选详情补采")
    sample_parser.add_argument("--keyword", action="append", help="只采集指定关键词，可重复传入")
    sample_parser.add_argument("--limit-per-keyword", type=int, default=50)
    sample_parser.add_argument("--delay-seconds", type=float, default=3.0)
    sample_parser.add_argument("--scroll-count", type=int, default=2)
    sample_parser.add_argument("--detail-start", type=int, default=0)
    sample_parser.add_argument("--detail-limit", type=int, default=50)
    sample_parser.add_argument("--detail-delay-seconds", type=float, default=2.0)
    sample_parser.add_argument("--skip-detail", action="store_true")
    sample_parser.add_argument("--debug", action="store_true")
    sample_parser.add_argument("--stamp", help="输出批次号，默认使用当前时间")
    sample_parser.add_argument("--output-dir", help="输出目录，默认写入 data-workflow/1688/runs/<stamp>")
    sample_parser.add_argument("--dry-run", action="store_true")
    sample_parser.set_defaults(func=sample)

    company_parser = subparsers.add_parser(
        "company",
        help="按单个 offer_id 采集商品关联店铺、公司档案和1688官方主体资质",
    )
    company_parser.add_argument("--offer-id", required=True)
    company_parser.add_argument("--output-dir", help="输出目录，默认写入 data-workflow/runtime/runs/1688")
    company_parser.add_argument("--delay-seconds", type=float, default=5.0)
    company_parser.add_argument("--profile-dir", help="自定义持久化浏览器登录态目录")
    company_parser.add_argument("--stamp", help="默认输出目录使用的批次时间戳")
    company_parser.add_argument("--debug", action="store_true")
    company_parser.add_argument("--headless", action="store_true")
    company_parser.add_argument("--dry-run", action="store_true")
    company_parser.set_defaults(func=company)

    multi_parser = subparsers.add_parser(
        "multi",
        help="按已选商品清单采集完整商品/SKU，并按 memberId 去重采集公司资产",
    )
    multi_parser.add_argument("--input", required=True, help="样本选择 JSON 文件")
    multi_parser.add_argument("--output-dir", help="批次输出目录")
    multi_parser.add_argument("--delay-seconds", type=float, default=5.0)
    multi_parser.add_argument("--profile-dir", help="自定义持久化浏览器登录态目录")
    multi_parser.add_argument("--stamp", help="默认输出目录使用的批次时间戳")
    multi_parser.add_argument("--debug", action="store_true")
    multi_parser.add_argument("--headless", action="store_true")
    multi_parser.add_argument("--dry-run", action="store_true")
    multi_parser.set_defaults(func=multi)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
