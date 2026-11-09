from __future__ import annotations

import pytest

from tiksocket.cli import build_parser, dump
from tiksocket.models import Chat


def parse(*args):
    return build_parser().parse_args(list(args))


def test_post_photos_arguments():
    args = parse("-a", "shop", "post", "photos", "a.jpg", "b.jpg", "--title", "Hi", "--sound", "lofi", "--dry-run")
    assert (args.account, args.command, args.kind, args.files, args.title, args.sound, args.dry_run) == \
        ("shop", "post", "photos", ["a.jpg", "b.jpg"], "Hi", "lofi", True)


def test_post_video_and_send_and_serve():
    assert parse("post", "video", "v.mp4", "--auto-sound").auto_sound
    send = parse("send", "0:1:1:2", "hello", "--client-id", "k1")
    assert (send.chat_id, send.text, send.client_id) == ("0:1:1:2", "hello", "k1")
    serve = parse("serve", "--port", "9000", "--token", "t", "--listen")
    assert (serve.port, serve.token, serve.listen) == (9000, "t", True)
    assert parse("serve").port == 8787


def test_command_required():
    with pytest.raises(SystemExit):
        parse()


def test_dump_dataclasses():
    assert dump([Chat(id="0:1:1:2", name="a")])[0]["name"] == "a"
