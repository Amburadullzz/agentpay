"""Build the AgentPay demo video from rendered frames + narration.

    .venv/bin/python demo/make_video.py

Outputs demo/agentpay-demo.mp4 (1920x1080, H.264 + AAC).
Narration: gTTS (British English). No cloud account, no API key.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from gtts import gTTS

ROOT = Path(__file__).parent
FRAMES = ROOT / "frames"
AUDIO = ROOT / "audio"
SEGMENTS = ROOT / "segments"
OUT = ROOT / "agentpay-demo.mp4"

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

NARRATION = {
    "01-title": "AgentPay. Policy-bound payments for AI agents. Built on the QDay Aevum testnet, settling in tUSD8.",
    "02-problem": (
        "An agent can already decide to buy something. Give it a funded wallet, and you are trusting it with "
        "unbounded authority. One hallucinated amount, one prompt injection, and the money is gone. And a limit "
        "written in the prompt is not a limit. It is a suggestion the agent can talk itself out of."
    ),
    "03-architecture": (
        "So the mandate lives on chain. A provider writes an invoice. The agent reads it, compares it against its "
        "mandate, and asks the vault to pay. The vault is the only component that holds money, and it answers one "
        "question: is this payment inside the mandate? A per transaction cap. A rolling daily cap. A payee allowlist. "
        "One payment per invoice. An approval threshold. Session expiry. And a pause switch. The agent key holds no "
        "owner rights at all."
    ),
    "04-dashboard": (
        "This is the live dashboard, reading straight from the chain. On the left, the mandate: three tenths per "
        "payment, eight tenths a day, and anything above two tenths needs a human. In the middle, the invoices. "
        "Invoice two, for fifty cents, stayed open, because it is over the per transaction cap. On the right, the "
        "audit trail: every payment, every approval, every pause."
    ),
    "05-beats": (
        "Five beats, all executed on the testnet. A fifteen cent invoice inside the mandate: paid, and a receipt NFT "
        "minted. A fifty cent invoice against a thirty cent cap: refused. A twenty five cent invoice above the approval "
        "threshold: the agent stopped, the owner signed off chain, the payment landed, and the nonce was consumed. "
        "Replaying a paid invoice reverts. And with the vault paused, the agent is blocked immediately."
    ),
    "06-safety": (
        "None of this is the agent being polite. Every control is a require in the contract, and every control has a "
        "test named after it. Thirty two tests pass, including fuzz tests over the cap boundaries, the replay paths, "
        "and per selector access control."
    ),
    "07-closing": (
        "AgentPay. A compromised agent can only spend inside its mandate. Contracts, agent, dashboard and tests are "
        "in the repository. Thank you."
    ),
}


def narrate() -> dict[str, Path]:
    AUDIO.mkdir(exist_ok=True)
    tracks = {}
    for name, text in NARRATION.items():
        path = AUDIO / f"{name}.mp3"
        if not path.exists():
            gTTS(text, lang="en", tld="co.uk").save(str(path))
            print("narration:", path.name)
        tracks[name] = path
    return tracks


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFMPEG, "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = stamp.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f"cannot read duration of {path}")


def build() -> None:
    tracks = narrate()
    SEGMENTS.mkdir(exist_ok=True)

    total = 0.0
    parts = []
    for frame in sorted(FRAMES.glob("*.png")):
        name = frame.stem
        audio = tracks[name]
        dur = duration(audio) + 0.9  # breathing room after each line
        seg = SEGMENTS / f"{name}.mp4"
        subprocess.run(
            [
                FFMPEG, "-y",
                "-loop", "1", "-framerate", "30", "-i", str(frame),
                "-i", str(audio),
                "-af", "apad=pad_dur=0.9",
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
                "-t", f"{dur:.2f}",
                "-movflags", "+faststart",
                str(seg),
            ],
            check=True,
            capture_output=True,
        )
        parts.append(seg)
        total += dur
        print(f"segment {name}: {dur:.1f}s")

    listfile = SEGMENTS / "concat.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", "-movflags", "+faststart", str(OUT)],
        check=True, capture_output=True,
    )
    print(f"\n{OUT}  {total:.1f}s  {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError as exc:
        print("ffmpeg failed:", exc.stderr.decode()[-800:] if exc.stderr else exc, file=sys.stderr)
        raise
