import asyncio
import sys

from tiksocket import TikSocket


async def main(paths):
    async with TikSocket("auth_info") as sock:
        result = await sock.post_photos(paths, "New listing #realestate #home", title="3 bedroom flat",
                                        sound="lofi", dry_run="--dry-run" in sys.argv)
        print(result)


asyncio.run(main([p for p in sys.argv[1:] if not p.startswith("--")]))
