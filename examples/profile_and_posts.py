import asyncio

from tiksocket import TikSocket


async def main():
    async with TikSocket("auth_info") as sock:
        me = await sock.update_profile(nickname="My Shop", bio="Open 9 to 6, DM us")
        print("profile", me.username, me.nickname, me.bio)

        mine = await sock.user_posts(limit=10)
        if mine:
            latest = mine[0]
            await sock.post_settings(latest.url, who_can_view="everyone", comments=True)
            await sock.pin_post(latest.url)
            await sock.download(latest.url, "latest.mp4")

        chat_id, sent = await sock.start_chat("@someone", "Hello, thanks for the follow", client_id="welcome-someone")
        print("chat", chat_id, sent.id)


asyncio.run(main())
