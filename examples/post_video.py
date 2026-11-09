import asyncio
import sys

from tiksocket import TikSocket


async def main(path):
    async with TikSocket("auth_info") as sock:
        result = await sock.post_video(path, "Posted with TikSocket #python", auto_sound=False)
        print(result.url)


asyncio.run(main(sys.argv[1]))
