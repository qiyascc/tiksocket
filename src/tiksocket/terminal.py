from __future__ import annotations

import io
import sys
from pathlib import Path

from .models import QRCode, VerifyPrompt


def qr_text(url: str) -> str:
    import qrcode

    code = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    code.add_data(url)
    code.make(fit=True)
    out = io.StringIO()
    code.print_ascii(out=out, invert=True)
    return out.getvalue()


def qr_svg(url: str) -> bytes:
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage, border=2)
    out = io.BytesIO()
    image.save(out)
    return out.getvalue()


def show_qr(qr: QRCode, folder: Path | None = None, stream=None) -> None:
    stream = stream or sys.stdout
    if qr.url:
        stream.write(qr_text(qr.url))
        stream.write("\nScan with the TikTok app: Profile > scan icon (top right).\n")
    if qr.image and folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "qr.png"
        path.write_bytes(qr.image)
        stream.write(f"QR image saved to {path}\n")
    stream.flush()


def show_prompt(prompt: VerifyPrompt, stream=None) -> None:
    stream = stream or sys.stdout
    stream.write(f"\nTikTok check: {prompt.title}\n")
    for line in prompt.lines:
        stream.write(f"  {line}\n")
    for button in prompt.buttons:
        stream.write(f"  [{button.get('i')}] {button.get('label')}\n")
    if prompt.captcha:
        stream.write("  TikTok shows a slider puzzle. Open the web UI (tiksocket serve) to solve it.\n")
    stream.flush()
