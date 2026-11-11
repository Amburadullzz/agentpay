"""Render the AgentPay demo video scenes (1920x1080 PNGs) from real project data.

    .venv/bin/python demo/render_video.py

Writes demo/frames/*.png. Narration and assembly live in demo/make_video.sh.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (11, 16, 32)
PANEL = (19, 26, 46)
TEXT = (232, 238, 252)
MUTED = (143, 160, 196)
GREEN = (74, 222, 128)
RED = (248, 113, 113)
AMBER = (251, 191, 36)
BLUE = (76, 141, 255)
VIOLET = (167, 139, 250)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
OUT = Path(__file__).parent / "frames"
ROOT = Path(__file__).parent.parent


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / "DejaVuSansMono.ttf"), size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # subtle top gradient bar
    for y in range(0, 8):
        d.line([(0, y), (W, y)], fill=(16, 24, 48))
    return img, d


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split():
            probe = f"{line} {word}".strip()
            if d.textlength(probe, font=f) <= width:
                line = probe
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def kicker(d, text, color=BLUE):
    d.text((120, 96), text.upper(), font=font(26, True), fill=color)


def headline(d, text, y=150, size=64, color=TEXT):
    lines = wrap(d, text, font(size, True), W - 240)
    for i, line in enumerate(lines):
        d.text((120, y + i * int(size * 1.25)), line, font=font(size, True), fill=color)
    return y + len(lines) * int(size * 1.25)


def bullets(d, items, y, size=34, color=MUTED, gap=18, width=W - 300):
    for item in items:
        color_here = color
        prefix = "•  "
        if item.startswith("!"):
            prefix, item, color_here = "✗  ", item[1:], RED
        elif item.startswith("+"):
            prefix, item, color_here = "✓  ", item[1:], GREEN
        lines = wrap(d, item, font(size), width)
        d.text((120, y), prefix, font=font(size, True), fill=color_here)
        for i, line in enumerate(lines):
            d.text((120 + 46, y + i * int(size * 1.3)), line, font=font(size), fill=color_here)
        y += len(lines) * int(size * 1.3) + gap
    return y


def panel(d, x, y, w, h, title=None, accent=PANEL):
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=PANEL, outline=(38, 50, 78), width=2)
    if title:
        d.text((x + 28, y + 22), title.upper(), font=font(22, True), fill=accent)


def save(img: Image.Image, name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name, "PNG")
    print("wrote", OUT / name)


# ------------------------------------------------------------------ scenes


def scene_title():
    img, d = canvas()
    d.text((120, 300), "AgentPay", font=font(140, True), fill=TEXT)
    d.text((120, 470), "Policy-bound payments for AI agents", font=font(56), fill=MUTED)
    d.line([(120, 590), (520, 590)], fill=BLUE, width=4)
    d.text((120, 630), "QDay Aevum Testnet  ·  chain 44005  ·  settlement in tUSD8", font=font(30), fill=MUTED)
    d.text((120, 690), "Aevum Builder Challenge #1  ·  Native AI Assistants", font=font(30), fill=VIOLET)
    save(img, "01-title.png")


def scene_problem():
    img, d = canvas()
    kicker(d, "the problem")
    y = headline(d, "An agent can already decide to pay.\nThe wallet is the hard part.")
    bullets(d, [
        "Give it a funded key and one hallucinated amount drains the account.",
        "Put the limit in the prompt and the agent can talk itself out of it.",
        "!Prompt instructions are not a security boundary.",
        "The mandate has to live somewhere the agent cannot edit.",
    ], y + 40)
    save(img, "02-problem.png")


def scene_architecture():
    img, d = canvas()
    kicker(d, "how it works")
    d.text((120, 140), "The agent proposes. The contract decides.", font=font(56, True), fill=TEXT)

    art = Image.open(ROOT / "assets" / "architecture.png").convert("RGB")
    target_w = 1680
    art = art.resize((target_w, int(art.height * target_w / art.width)), Image.LANCZOS)
    img.paste(art, ((W - target_w) // 2, 260))
    d.text((120, 260 + art.height + 24),
           "Caps, allowlist, idempotency, approval threshold, expiry and the pause switch are enforced on-chain.",
           font=font(26), fill=MUTED)
    save(img, "03-architecture.png")


def scene_dashboard():
    img, d = canvas()
    kicker(d, "live on testnet")
    d.text((120, 140), "Every invoice, every decision, on chain.", font=font(56, True), fill=TEXT)

    shot = Image.open(ROOT / "assets" / "dashboard.png").convert("RGB")
    target_w = 1680
    shot = shot.resize((target_w, int(shot.height * target_w / shot.width)), Image.LANCZOS)
    img.paste(shot, ((W - target_w) // 2, 250))

    d.rounded_rectangle([120, 250 + shot.height + 18, W - 120, 250 + shot.height + 18 + 96],
                        radius=14, fill=PANEL, outline=(38, 50, 78), width=2)
    d.text((150, 250 + shot.height + 40),
           "Invoice #2 (0.50 tUSD8) stayed open: over the per-tx cap. Invoice #3 needed the owner's signature.",
           font=font(26), fill=MUTED)
    save(img, "04-dashboard.png")


def scene_beats():
    img, d = canvas()
    kicker(d, "the demo, as it ran on chain")
    d.text((120, 140), "Five beats, five different answers.", font=font(56, True), fill=TEXT)

    rows = [
        ("1", "0.15 invoice, inside mandate", "paid · receipt #1 minted", GREEN),
        ("2", "0.50 invoice, cap is 0.30", "REFUSED — CAP_EXCEEDED", RED),
        ("3", "0.25 invoice, threshold 0.20", "owner signed EIP-712, then paid", AMBER),
        ("4", "replay of a paid invoice", "revert — AlreadyPaid", RED),
        ("5", "vault paused, invoice arrives", "REFUSED — VAULT_PAUSED, then paid", AMBER),
    ]
    y = 300
    for num, what, result, color in rows:
        d.rounded_rectangle([120, y, W - 120, y + 118], radius=14, fill=PANEL, outline=(38, 50, 78), width=2)
        d.ellipse([150, y + 34, 200, y + 84], outline=color, width=3)
        d.text((166, y + 44), num, font=font(30, True), fill=color)
        d.text((228, y + 30), what, font=font(32, True), fill=TEXT)
        d.text((228, y + 72), result, font=font(26), fill=color)
        y += 136
    save(img, "05-beats.png")


def scene_safety():
    img, d = canvas()
    kicker(d, "safety, trust and controls", GREEN)
    d.text((120, 140), "Every guarantee has a test with its name on it.", font=font(54, True), fill=TEXT)

    left = [
        "per-transaction cap",
        "rolling 24h cap",
        "payee allowlist",
        "one payment per invoice",
        "approval threshold",
        "approval replay protection",
    ]
    right = [
        "session expiry",
        "instant revocation",
        "kill switch",
        "agent key ≠ owner key",
        "verifiable receipt NFT",
        "vault-only settlement",
    ]
    y = 300
    for a, b in zip(left, right):
        d.text((140, y), "✓", font=font(28, True), fill=GREEN)
        d.text((180, y), a, font=font(28), fill=TEXT)
        d.text((1000, y), "✓", font=font(28, True), fill=GREEN)
        d.text((1040, y), b, font=font(28), fill=TEXT)
        y += 62

    panel(d, 120, 760, W - 240, 180)
    d.text((150, 790), "forge test  →  57 passed  ·  100% line coverage", font=mono(38), fill=GREEN)
    d.text((150, 856), "includes fuzz tests over cap boundaries, replay paths and per-selector access control",
           font=font(26), fill=MUTED)
    save(img, "08-safety.png")


def scene_closing():
    img, d = canvas()
    d.text((120, 300), "AgentPay", font=font(110, True), fill=TEXT)
    d.text((120, 440), "A compromised agent can only spend inside its mandate.", font=font(44), fill=MUTED)
    d.line([(120, 540), (620, 540)], fill=GREEN, width=4)

    dep = json.loads((ROOT / "deployments" / "aevum.json").read_text())
    y = 600
    d.text((120, y), "PolicyVault", font=font(28), fill=MUTED)
    d.text((400, y), dep["contracts"]["vault"]["address"], font=mono(28), fill=TEXT)
    d.text((120, y + 50), "Registry   ", font=font(28), fill=MUTED)
    d.text((400, y + 50), dep["contracts"]["registry"]["address"], font=mono(28), fill=TEXT)
    d.text((120, y + 100), "Receipts   ", font=font(28), fill=MUTED)
    d.text((400, y + 100), dep["contracts"]["receipts"]["address"], font=mono(28), fill=TEXT)

    d.text((120, 900), "github.com/Amburadullzz/agentpay", font=mono(32), fill=BLUE)
    save(img, "09-closing.png")


def scene_attacks():
    img, d = canvas()
    kicker(d, "we attacked it ourselves", RED)
    d.text((120, 140), "Eight attacks. Eight refusals.", font=font(56, True), fill=TEXT)

    rows = [
        ("pay a non-allowlisted address", "PayeeNotAllowed"),
        ("pay over the per-transaction cap", "CapExceeded"),
        ("replay an invoice already paid", "AlreadyPaid"),
        ("raise its own limits", "OwnableUnauthorizedAccount"),
        ("pause or unpause the vault", "OwnableUnauthorizedAccount"),
        ("withdraw the balance", "OwnableUnauthorizedAccount"),
        ("whitelist an attacker address", "OwnableUnauthorizedAccount"),
        ("submit a forged approval", "BadApproval"),
    ]
    y = 280
    for i, (attack, error) in enumerate(rows, 1):
        d.rounded_rectangle([120, y, W - 120, y + 76], radius=12, fill=PANEL, outline=(38, 50, 78), width=2)
        d.text((150, y + 24), f"{i}", font=font(26, True), fill=MUTED)
        d.text((196, y + 22), attack, font=font(28), fill=TEXT)
        d.text((1160, y + 22), "BLOCKED", font=font(24, True), fill=GREEN)
        d.text((1300, y + 24), error, font=mono(22), fill=RED)
        y += 88

    d.text((120, y + 24), "run with the agent key as the attacker — every reason above is the contract's own revert",
           font=font(24), fill=MUTED)
    save(img, "07-attacks.png")


def scene_payroll():
    img, d = canvas()
    kicker(d, "second workflow on the same vault", VIOLET)
    d.text((120, 140), "Payroll is the same flow, repeated.", font=font(54, True), fill=TEXT)

    d.text((120, 250), "before the owner allowlists the payees", font=font(26), fill=MUTED)
    y = 292
    for name, amt in (("rafi", "0.05"), ("nadia", "0.05"), ("bima", "0.05")):
        d.rounded_rectangle([120, y, W - 120, y + 70], radius=12, fill=PANEL, outline=(38, 50, 78), width=2)
        d.text((150, y + 20), name, font=font(28), fill=TEXT)
        d.text((330, y + 20), amt, font=mono(26), fill=MUTED)
        d.text((1160, y + 20), "REFUSE", font=font(24, True), fill=RED)
        d.text((1290, y + 22), "PAYEE_NOT_ALLOWED", font=mono(22), fill=RED)
        y += 82

    d.text((120, y + 16), "after --allowlist, one agent pass", font=font(26), fill=MUTED)
    y += 60
    for name, amt in (("rafi", "0.05"), ("nadia", "0.05"), ("bima", "0.05")):
        d.rounded_rectangle([120, y, W - 120, y + 70], radius=12, fill=PANEL, outline=(30, 70, 48), width=2)
        d.text((150, y + 20), name, font=font(28), fill=TEXT)
        d.text((330, y + 20), amt, font=mono(26), fill=MUTED)
        d.text((1160, y + 20), "PAID", font=font(24, True), fill=GREEN)
        d.text((1290, y + 22), "3/3 settled · 0.15 tUSD8", font=mono(22), fill=GREEN)
        y += 82

    save(img, "06-payroll.png")


if __name__ == "__main__":
    scene_title()
    scene_problem()
    scene_architecture()
    scene_dashboard()
    scene_beats()
    scene_payroll()
    scene_attacks()
    scene_safety()
    scene_closing()
