import asyncio

from tiksocket import RequestPending, make_tiktok_socket, use_multi_file_auth_state
from tiksocket.terminal import show_qr


async def main():
    sock = make_tiktok_socket(use_multi_file_auth_state("auth_info"))
    sock.on("qr", show_qr)

    @sock.on("messages.upsert")
    async def on_message(event):
        for message in event["messages"]:
            if message.from_me or message.kind != "text":
                continue
            try:
                await sock.send_message(message.chat_id, f"You said: {message.text}", client_id=f"echo-{message.id}")
            except RequestPending:
                print("This person has not accepted the message request yet")

    if await sock.connect() is None:
        await sock.wait_for_login()
    await sock.start_listening(interval=20)


asyncio.run(main())
