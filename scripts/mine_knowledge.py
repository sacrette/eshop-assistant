import asyncio

from app.kb import mining


async def main() -> None:
    stats = await mining.mine()
    print(f"✅ 挖知识:{stats}")


if __name__ == "__main__":
    asyncio.run(main())
