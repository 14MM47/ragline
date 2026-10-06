"""ACL crawl entry point — run by ragline-acl.timer (or by hand).

    uv run python scripts/acl_crawl.py [--concurrency N]

Reads the same .env as the app (CWD or absolute paths in production), crawls
every ready document's original_path, and exits non-zero when the crawl
could not run at all — so systemd's OnFailure= alerting fires. Per-document
failures are NOT fatal; they land in DocumentAcl.crawl_status and the admin
/api/admin/acl-status view.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragline.acl.crawler import crawl_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl NTFS DACLs for all ready documents")
    parser.add_argument("--concurrency", type=int, default=8, help="parallel SMB fetches")
    args = parser.parse_args()

    try:
        stats = asyncio.run(crawl_all(concurrency=args.concurrency))
    except Exception as e:
        print(f"acl crawl failed to run: {e}", file=sys.stderr)
        return 1

    print("acl crawl finished:", stats.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
