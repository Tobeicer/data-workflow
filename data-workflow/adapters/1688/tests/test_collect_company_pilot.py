import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import collect_company_pilot  # noqa: E402


def test_account_contact_remediation_redirect_requires_human_action() -> None:
    page = collect_company_pilot.CapturedPage(
        page_type="product",
        requested_url="https://detail.1688.com/offer/994122564753.html",
        final_url=(
            "https://member.1688.com/member/modify_evolve.htm"
            "?infoCheck=contactinfo_invalid"
        ),
        title="阿里巴巴·商人自己的网站",
        html="",
        text="",
    )

    assert (
        collect_company_pilot.restriction_status(page)
        == "human_verification_required"
    )
