import asyncio
import sys

from app.core.flywheel import process_pending


async def main():
    stats = await process_pending(limit=200)
    print(f"本轮处理 {stats['processed']} 条:新建缺口 {stats['created']},"
          f"归并 {stats['merged']},跳过待重试 {stats['skipped']}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
