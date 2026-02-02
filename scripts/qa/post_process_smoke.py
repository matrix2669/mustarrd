import argparse
import asyncio
from pathlib import Path

from services.post_processor import PostProcessor, HardwareAccel, OutputFormat


def _parse_hw_accel(value: str) -> HardwareAccel:
    value = value.strip().lower()
    mapping = {
        "cpu": HardwareAccel.CPU,
        "vaapi": HardwareAccel.VAAPI,
        "nvenc": HardwareAccel.NVIDIA,
        "amf": HardwareAccel.AMD,
        "videotoolbox": HardwareAccel.APPLE_SILICON,
    }
    if value not in mapping:
        raise ValueError(f"Unsupported hw accel: {value}")
    return mapping[value]


def _parse_format(value: str) -> OutputFormat:
    value = value.strip().lower()
    mapping = {
        "mp4": OutputFormat.MP4,
        "mkv": OutputFormat.MKV,
        "ts": OutputFormat.TS,
    }
    if value not in mapping:
        raise ValueError(f"Unsupported format: {value}")
    return mapping[value]


async def _run(args: argparse.Namespace) -> str:
    processor = PostProcessor()
    hw_accel = _parse_hw_accel(args.hw_accel)
    output_format = _parse_format(args.format)
    return await processor.remove_commercials(
        input_path=args.input,
        edl_path=args.edl,
        output_format=output_format,
        hw_accel=hw_accel,
        remux_only=args.remux_only,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Comskip/ffmpeg smoke test runner.")
    parser.add_argument("--input", required=True, help="Path to input video")
    parser.add_argument("--edl", required=True, help="Path to EDL file")
    parser.add_argument("--format", default="mp4", help="Output format: mp4|mkv|ts")
    parser.add_argument("--hw-accel", default="cpu", help="cpu|vaapi|nvenc|amf|videotoolbox")
    parser.add_argument("--remux-only", action="store_true", help="Skip re-encode for mp4/mkv")
    args = parser.parse_args()

    for path in (args.input, args.edl):
        if not Path(path).exists():
            raise SystemExit(f"Missing file: {path}")

    output_path = asyncio.run(_run(args))
    print(output_path)


if __name__ == "__main__":
    main()
