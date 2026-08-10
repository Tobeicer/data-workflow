from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC_DIR = Path(__file__).resolve().parent
WORKFLOW_DIR = Path(__file__).resolve().parents[3]
RUNS_DIR = WORKFLOW_DIR / "runtime" / "runs" / "1688"
DEFAULT_CATEGORY_CONFIG = SRC_DIR.parent / "config" / "validation_categories.json"


def run_command(command: list[str], *, dry_run: bool) -> None:
    print("[1688-workflow] " + " ".join(command))
    if dry_run:
        return
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def add_repeated_option(command: list[str], option: str, values: list[str] | None) -> None:
    for value in values or []:
        command.extend([option, value])


def add_browser_pacing_options(command: list[str], args: argparse.Namespace) -> None:
    """透传 stealth 与自适应频控参数到浏览器采集脚本。"""
    if getattr(args, "no_stealth", False):
        command.append("--no-stealth")
    pacing_config = getattr(args, "pacing_config", None)
    if pacing_config:
        command.extend(["--pacing-config", pacing_config])
        command.extend(["--pacing-checkpoint", args.pacing_checkpoint])
        daily_cap = getattr(args, "daily_cap", None)
        if daily_cap:
            command.extend(["--daily-cap", str(daily_cap)])


def load_keywords(config_path: Path) -> list[str]:
    """从分类配置 JSON 读取启用关键词。

    兼容三种词条：
    - 字符串（旧验证配置 validation_categories.json，直接启用）；
    - 对象 keywords（keywords.json 旧平铺结构，仅 active 参与）；
    - concepts（keywords.json 概念-别名结构：active 概念的 standard_name + aliases 展开）。
    """
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    categories = config_payload.get("categories", [])
    keywords: list[str] = []
    for category in categories:
        if category.get("concepts"):
            for concept in category["concepts"]:
                if concept.get("status") != "active":
                    continue
                name = concept.get("standard_name")
                if name:
                    keywords.append(name)
                for alias in concept.get("aliases", []):
                    if alias:
                        keywords.append(alias)
        else:
            for keyword in category.get("keywords", []):
                if isinstance(keyword, str):
                    if keyword:
                        keywords.append(keyword)
                elif isinstance(keyword, dict):
                    term = keyword.get("term")
                    if term and keyword.get("status") == "active":
                        keywords.append(str(term))
    if not keywords:
        raise SystemExit("category config must contain active keywords")
    return keywords


def prepare_login(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(SRC_DIR / "collect_1688_public_sample.py"),
        "--prepare-login",
        "--login-wait-seconds",
        str(args.login_wait_seconds),
    ]
    run_command(command, dry_run=args.dry_run)


def prepare_verification(args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(SRC_DIR / "collect_1688_public_sample.py"),
        "--prepare-verification",
        "--keyword",
        args.keyword,
        "--verification-wait-seconds",
        str(args.verification_wait_seconds),
    ]
    run_command(command, dry_run=args.dry_run)


def sample(args: argparse.Namespace) -> None:
    stamp = args.stamp or ("dry_run" if args.dry_run else datetime.now().strftime("%Y%m%d_%H%M%S"))
    output_dir = Path(args.output_dir) if args.output_dir else RUNS_DIR / stamp

    list_csv = output_dir / f"1688_offer_index_{stamp}.csv"
    relevant_csv = output_dir / f"1688_relevant_offer_index_{stamp}.csv"
    detail_csv = output_dir / f"1688_relevant_product_detail_{stamp}.csv"
    sku_csv = output_dir / f"1688_relevant_product_sku_{stamp}.csv"

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    list_command = [
        sys.executable,
        str(SRC_DIR / "collect_1688_public_sample.py"),
        "--output",
        str(list_csv),
        "--limit-per-keyword",
        str(args.limit_per_keyword),
        "--delay-seconds",
        str(args.delay_seconds),
        "--scroll-count",
        str(args.scroll_count),
    ]
    keywords = (
        load_keywords(Path(args.category_config))
        if args.category_config
        else args.keyword
    )
    if not keywords:
        raise SystemExit("sample requires --keyword or --category-config")
    add_repeated_option(list_command, "--keyword", keywords)
    if args.debug:
        list_command.append("--debug")
    run_command(list_command, dry_run=args.dry_run)

    filter_command = [
        sys.executable,
        str(SRC_DIR / "filter_1688_relevant.py"),
        "--input",
        str(list_csv),
        "--output",
        str(relevant_csv),
    ]
    run_command(filter_command, dry_run=args.dry_run)

    if not args.skip_detail:
        detail_command = [
            sys.executable,
            str(SRC_DIR / "collect_1688_detail_sample.py"),
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
        else RUNS_DIR / f"1688_company_{stamp}"
    )
    collector = SRC_DIR / "collect_company_pilot.py"
    command = [
        sys.executable,
        str(collector),
        "--offer-id",
        args.offer_id,
        "--output-dir",
        str(output_dir),
        "--delay-seconds",
        str(args.delay_seconds),
        "--verification-wait-seconds",
        str(args.verification_wait_seconds),
    ]
    if args.profile_dir:
        command.extend(["--profile-dir", args.profile_dir])
    if args.debug:
        command.append("--debug")
    if args.headless:
        command.append("--headless")
    add_browser_pacing_options(command, args)
    run_command(command, dry_run=args.dry_run)
    print("[1688-workflow] 公司试采输出目录：" + str(output_dir))


def multi(args: argparse.Namespace) -> None:
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else RUNS_DIR / f"1688_multi_{stamp}"
    )
    collector = SRC_DIR / "multi_product_workflow.py"
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
    add_browser_pacing_options(command, args)
    run_command(command, dry_run=args.dry_run)
    print("[1688-workflow] 多商品批次输出目录：" + str(output_dir))


def validate(args: argparse.Namespace) -> None:
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else RUNS_DIR / f"1688_validation_{stamp}"
    )
    category_config = Path(args.category_config) if args.category_config else DEFAULT_CATEGORY_CONFIG
    keywords = load_keywords(category_config)
    candidate_csv = output_dir / "candidate_offers.csv"
    selected_json = output_dir / "selected_samples.json"
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    discover_command = [
        sys.executable,
        str(SRC_DIR / "collect_1688_public_sample.py"),
        "--output",
        str(candidate_csv),
        "--limit-per-keyword",
        str(args.limit_per_keyword),
        "--delay-seconds",
        str(args.delay_seconds),
        "--scroll-count",
        str(args.scroll_count),
    ]
    add_repeated_option(discover_command, "--keyword", keywords)
    if args.debug:
        discover_command.append("--debug")
    run_command(discover_command, dry_run=args.dry_run)

    select_command = [
        sys.executable,
        str(SRC_DIR / "sample_selector.py"),
        "--input",
        str(candidate_csv),
        "--output",
        str(selected_json),
        "--category-config",
        str(category_config),
    ]
    run_command(select_command, dry_run=args.dry_run)

    multi_command = [
        sys.executable,
        str(SRC_DIR / "multi_product_workflow.py"),
        "--input",
        str(selected_json),
        "--output-dir",
        str(output_dir),
        "--delay-seconds",
        str(args.collection_delay_seconds),
        "--confirmation-window",
        str(args.confirmation_window),
    ]
    if args.profile_dir:
        multi_command.extend(["--profile-dir", args.profile_dir])
    if args.debug:
        multi_command.append("--debug")
    if args.headless:
        multi_command.append("--headless")
    add_browser_pacing_options(multi_command, args)
    run_command(multi_command, dry_run=args.dry_run)
    print("[1688-workflow] 分类覆盖验证输出目录：" + str(output_dir))


def main() -> None:
    parser = argparse.ArgumentParser(description="1688 补充性商品样本采集工作流入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("prepare-login", help="打开 1688 登录页并保存本地浏览器登录态")
    login_parser.add_argument("--login-wait-seconds", type=int, default=240)
    login_parser.add_argument("--dry-run", action="store_true")
    login_parser.set_defaults(func=prepare_login)

    verification_parser = subparsers.add_parser(
        "prepare-verification",
        help="打开受限搜索页，等待人工完成滑块并保存本地浏览器状态",
    )
    verification_parser.add_argument("--keyword", required=True)
    verification_parser.add_argument("--verification-wait-seconds", type=int, default=240)
    verification_parser.add_argument("--dry-run", action="store_true")
    verification_parser.set_defaults(func=prepare_verification)

    sample_parser = subparsers.add_parser("sample", help="执行列表采样、相关性筛选和可选详情补采")
    sample_parser.add_argument("--keyword", action="append", help="只采集指定关键词，可重复传入")
    sample_parser.add_argument("--category-config", help="关键词库配置 JSON（keywords.json/validation_categories.json）")
    sample_parser.add_argument("--limit-per-keyword", type=int, default=50)
    sample_parser.add_argument("--delay-seconds", type=float, default=8.0)
    sample_parser.add_argument("--scroll-count", type=int, default=2)
    sample_parser.add_argument("--detail-start", type=int, default=0)
    sample_parser.add_argument("--detail-limit", type=int, default=50)
    sample_parser.add_argument("--detail-delay-seconds", type=float, default=6.0)
    sample_parser.add_argument("--skip-detail", action="store_true")
    sample_parser.add_argument("--debug", action="store_true")
    sample_parser.add_argument("--stamp", help="输出批次号，默认使用当前时间")
    sample_parser.add_argument("--output-dir", help="输出目录，默认写入 runtime/runs/1688/<run_id>")
    sample_parser.add_argument("--dry-run", action="store_true")
    sample_parser.set_defaults(func=sample)

    company_parser = subparsers.add_parser(
        "company",
        help="按单个 offer_id 采集商品关联店铺、公司档案和1688官方主体资质",
    )
    company_parser.add_argument("--offer-id", required=True)
    company_parser.add_argument("--output-dir", help="输出目录，默认写入 runtime/runs/1688")
    company_parser.add_argument("--delay-seconds", type=float, default=8.0)
    company_parser.add_argument("--profile-dir", help="自定义持久化浏览器登录态目录")
    company_parser.add_argument("--stamp", help="默认输出目录使用的批次时间戳")
    company_parser.add_argument("--debug", action="store_true")
    company_parser.add_argument("--headless", action="store_true")
    company_parser.add_argument("--verification-wait-seconds", type=int, default=240)
    company_parser.add_argument("--no-stealth", action="store_true")
    company_parser.add_argument("--pacing-config", help="自适应频控配置 JSON")
    company_parser.add_argument("--pacing-checkpoint", default=str(WORKFLOW_DIR / "runtime" / "state" / "1688_pacing.json"))
    company_parser.add_argument("--daily-cap", type=int)
    company_parser.add_argument("--dry-run", action="store_true")
    company_parser.set_defaults(func=company)

    multi_parser = subparsers.add_parser(
        "multi",
        help="按已选商品清单采集完整商品/SKU，并按 memberId 去重采集公司资产",
    )
    multi_parser.add_argument("--input", required=True, help="样本选择 JSON 文件")
    multi_parser.add_argument("--output-dir", help="批次输出目录")
    multi_parser.add_argument("--delay-seconds", type=float, default=8.0)
    multi_parser.add_argument("--profile-dir", help="自定义持久化浏览器登录态目录")
    multi_parser.add_argument("--stamp", help="默认输出目录使用的批次时间戳")
    multi_parser.add_argument("--debug", action="store_true")
    multi_parser.add_argument("--headless", action="store_true")
    multi_parser.add_argument("--no-stealth", action="store_true")
    multi_parser.add_argument("--pacing-config", help="自适应频控配置 JSON")
    multi_parser.add_argument("--pacing-checkpoint", default=str(WORKFLOW_DIR / "runtime" / "state" / "1688_pacing.json"))
    multi_parser.add_argument("--daily-cap", type=int)
    multi_parser.add_argument("--dry-run", action="store_true")
    multi_parser.set_defaults(func=multi)

    validate_parser = subparsers.add_parser(
        "validate",
        help="按正式分类执行候选发现、分类选样和商品/公司全字段验证批次",
    )
    validate_parser.add_argument("--category-config", help="分类验证配置 JSON")
    validate_parser.add_argument("--limit-per-keyword", type=int, default=3)
    validate_parser.add_argument("--delay-seconds", type=float, default=8.0)
    validate_parser.add_argument("--scroll-count", type=int, default=1)
    validate_parser.add_argument("--collection-delay-seconds", type=float, default=8.0)
    validate_parser.add_argument("--confirmation-window", type=int, default=10)
    validate_parser.add_argument("--profile-dir", help="自定义持久化浏览器登录态目录")
    validate_parser.add_argument("--stamp", help="默认输出目录使用的批次时间戳")
    validate_parser.add_argument("--output-dir", help="批次输出目录")
    validate_parser.add_argument("--debug", action="store_true")
    validate_parser.add_argument("--headless", action="store_true")
    validate_parser.add_argument("--no-stealth", action="store_true")
    validate_parser.add_argument("--pacing-config", help="自适应频控配置 JSON")
    validate_parser.add_argument("--pacing-checkpoint", default=str(WORKFLOW_DIR / "runtime" / "state" / "1688_pacing.json"))
    validate_parser.add_argument("--daily-cap", type=int)
    validate_parser.add_argument("--dry-run", action="store_true")
    validate_parser.set_defaults(func=validate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
