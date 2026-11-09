import asyncio

from tiksocket import TikSocket


async def main():
    async with TikSocket("auth_info") as sock:
        user = await sock.get_user("@tiktok")
        print(user.nickname, user.followers, "following" if user.is_following else "not following")

        page = await sock.followers("@tiktok", count=20)
        print([u.username for u in page.items], "next cursor", page.cursor)

        posts = await sock.user_posts("@tiktok", limit=5)
        for post in posts:
            print(post.url, post.likes, post.comments)

        if posts:
            first = posts[0]
            for comment in await sock.comments(first.url, limit=10):
                print(comment.author, comment.text)
            await sock.like(first.url)
            await sock.favorite(first.url)

        await sock.follow("@tiktok")

        for post in await sock.feed("foryou", count=5):
            print(post.author, post.caption[:60])

        for notice in await sock.notifications(count=10, kind="comment"):
            print(notice.users, notice.text)


asyncio.run(main())
