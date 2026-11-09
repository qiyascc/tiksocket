import asyncio

from tiksocket import TikSocket
from tiksocket.terminal import show_prompt, show_qr


async def main():
    sock = TikSocket("auth_info")
    sock.on("qr", show_qr)
    sock.on("connection.update", print)

    @sock.on("verify")
    async def on_verify(prompt):
        show_prompt(prompt)
        if prompt.needs_code:
            code = await asyncio.to_thread(input, "Code: ")
            await sock.submit_code(code)

    profile = await sock.connect()
    profile = profile or await sock.wait_for_login(timeout=300)
    print("Logged in as", profile.username)
    await sock.close()


asyncio.run(main())
