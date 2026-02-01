import asyncio
import os
import shutil
import platform
import subprocess
from typing import Optional, Callable, List, Dict
from enum import Enum


class OutputFormat(str, Enum):
    TS = "ts"
    MP4 = "mp4"
    MKV = "mkv"


class HardwareAccel(str, Enum):
    CPU = "cpu"
    APPLE_SILICON = "videotoolbox"  # macOS VideoToolbox (M1/M2/etc)
    NVIDIA = "nvenc"  # NVIDIA NVENC
    AMD = "amf"  # AMD AMF
    INTEL = "qsv"  # Intel QuickSync
    VAAPI = "vaapi"  # Linux VA-API (Intel/AMD)


# Encoder mappings for each hardware acceleration method
ENCODER_MAP = {
    HardwareAccel.CPU: {
        "h264": "libx264",
        "hevc": "libx265",
    },
    HardwareAccel.APPLE_SILICON: {
        "h264": "h264_videotoolbox",
        "hevc": "hevc_videotoolbox",
    },
    HardwareAccel.NVIDIA: {
        "h264": "h264_nvenc",
        "hevc": "hevc_nvenc",
    },
    HardwareAccel.AMD: {
        "h264": "h264_amf",
        "hevc": "hevc_amf",
    },
    HardwareAccel.INTEL: {
        "h264": "h264_qsv",
        "hevc": "hevc_qsv",
    },
    HardwareAccel.VAAPI: {
        "h264": "h264_vaapi",
        "hevc": "hevc_vaapi",
    },
}


class PostProcessor:
    """Handles transcoding and commercial detection/removal."""

    def __init__(self):
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._comskip_path = shutil.which("comskip")
        self._available_encoders: Optional[List[str]] = None

    def _resolve_ffmpeg_path(self) -> Optional[str]:
        """Resolve ffmpeg path on demand to handle PATH changes."""
        candidates = []
        env_path = os.environ.get("CATCHUP_FFMPEG_PATH") or os.environ.get("FFMPEG_PATH")
        if env_path:
            candidates.append(env_path)
        if self._ffmpeg_path:
            candidates.append(self._ffmpeg_path)

        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            candidates.append(system_ffmpeg)
        candidates.extend([
            "/usr/local/bin/ffmpeg",
            "/usr/bin/ffmpeg",
        ])

        for path in candidates:
            if not path:
                continue
            if os.path.isfile(path) and os.access(path, os.X_OK):
                self._ffmpeg_path = path
                return self._ffmpeg_path

        self._ffmpeg_path = None
        return None

    def _resolve_comskip_path(self) -> Optional[str]:
        """Resolve comskip path on demand to handle PATH changes."""
        candidates = []
        env_path = os.environ.get("CATCHUP_COMSKIP_PATH") or os.environ.get("COMSKIP_PATH")
        if env_path:
            candidates.append(env_path)
        if self._comskip_path:
            candidates.append(self._comskip_path)
        system_comskip = shutil.which("comskip")
        if system_comskip:
            candidates.append(system_comskip)

        for path in candidates:
            if not path:
                continue
            if os.path.isfile(path) and os.access(path, os.X_OK):
                self._comskip_path = path
                return self._comskip_path

        self._comskip_path = None
        return None

    def get_ffmpeg_path(self) -> Optional[str]:
        """Return resolved ffmpeg path if available."""
        return self._resolve_ffmpeg_path()

    @property
    def ffmpeg_available(self) -> bool:
        return self._resolve_ffmpeg_path() is not None

    @property
    def comskip_available(self) -> bool:
        return self._resolve_comskip_path() is not None

    def set_comskip_path(self, path: str):
        """Set custom path to comskip binary."""
        if os.path.isfile(path):
            self._comskip_path = path

    def set_ffmpeg_path(self, path: str):
        """Set custom path to ffmpeg binary."""
        if os.path.isfile(path):
            self._ffmpeg_path = path

    def _get_available_encoders(self) -> List[str]:
        """Get list of available ffmpeg encoders."""
        if self._available_encoders is not None:
            return self._available_encoders

        if not self.ffmpeg_available:
            return []

        try:
            result = subprocess.run(
                [self._ffmpeg_path, "-encoders", "-hide_banner"],
                capture_output=True,
                text=True,
                timeout=10
            )
            self._available_encoders = result.stdout
            return self._available_encoders
        except Exception:
            return []

    def get_available_hardware_accels(self) -> List[Dict]:
        """Detect which hardware acceleration methods are available."""
        available = []
        encoders = self._get_available_encoders()

        # Always add CPU
        available.append({
            "id": HardwareAccel.CPU.value,
            "name": "CPU (Software)",
            "description": "Universal compatibility, slower",
            "available": True,
        })

        # Check Apple Silicon (macOS only)
        if platform.system() == "Darwin":
            if "h264_videotoolbox" in encoders:
                available.append({
                    "id": HardwareAccel.APPLE_SILICON.value,
                    "name": "Apple Silicon (VideoToolbox)",
                    "description": "Hardware acceleration for M1/M2/M3 Macs",
                    "available": True,
                })

        # Check NVIDIA
        if "h264_nvenc" in encoders:
            available.append({
                "id": HardwareAccel.NVIDIA.value,
                "name": "NVIDIA (NVENC)",
                "description": "Hardware acceleration for NVIDIA GPUs",
                "available": True,
            })

        # Check AMD
        if "h264_amf" in encoders:
            available.append({
                "id": HardwareAccel.AMD.value,
                "name": "AMD (AMF)",
                "description": "Hardware acceleration for AMD GPUs",
                "available": True,
            })

        # Check Intel QuickSync
        if "h264_qsv" in encoders:
            available.append({
                "id": HardwareAccel.INTEL.value,
                "name": "Intel (QuickSync)",
                "description": "Hardware acceleration for Intel CPUs/GPUs",
                "available": True,
            })

        # Check VA-API (Linux)
        if platform.system() == "Linux" and "h264_vaapi" in encoders:
            available.append({
                "id": HardwareAccel.VAAPI.value,
                "name": "VA-API (Linux)",
                "description": "Hardware acceleration via VA-API",
                "available": True,
            })

        return available

    def _get_encoder_args(
        self,
        hw_accel: HardwareAccel,
        codec: str = "h264",
        quality: str = "balanced"
    ) -> List[str]:
        """Get ffmpeg encoder arguments for the specified hardware acceleration."""
        encoder = ENCODER_MAP.get(hw_accel, {}).get(codec, "libx264")

        # Quality presets
        quality_map = {
            "fast": {"cpu_preset": "veryfast", "hw_quality": "speed"},
            "balanced": {"cpu_preset": "fast", "hw_quality": "balanced"},
            "quality": {"cpu_preset": "slow", "hw_quality": "quality"},
        }
        q = quality_map.get(quality, quality_map["balanced"])

        args = ["-c:v", encoder]

        if hw_accel == HardwareAccel.CPU:
            args.extend([
                "-preset", q["cpu_preset"],
                "-crf", "22",
            ])
        elif hw_accel == HardwareAccel.APPLE_SILICON:
            # VideoToolbox options
            args.extend([
                "-q:v", "65",  # Quality (0-100, higher is better)
                "-allow_sw", "1",  # Allow software fallback
            ])
        elif hw_accel == HardwareAccel.NVIDIA:
            args.extend([
                "-preset", "p4" if q["hw_quality"] == "speed" else "p5",
                "-rc", "vbr",
                "-cq", "23",
            ])
        elif hw_accel == HardwareAccel.AMD:
            args.extend([
                "-quality", q["hw_quality"],
                "-rc", "vbr_latency",
            ])
        elif hw_accel == HardwareAccel.INTEL:
            args.extend([
                "-preset", "faster" if q["hw_quality"] == "speed" else "balanced",
                "-global_quality", "23",
            ])
        elif hw_accel == HardwareAccel.VAAPI:
            args.extend([
                "-vaapi_device", "/dev/dri/renderD128",
                "-vf", "format=nv12,hwupload",
            ])

        return args

    def _parse_ffmpeg_time(self, key: str, value: str) -> Optional[float]:
        """Parse ffmpeg progress time values into seconds."""
        try:
            if key in ("out_time_ms", "out_time_us"):
                # ffmpeg reports microseconds for both out_time_ms and out_time_us
                micros = int(value)
                return micros / 1_000_000
            if key == "out_time":
                # Format: HH:MM:SS.micro
                parts = value.split(":")
                if len(parts) != 3:
                    return None
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                return (hours * 3600) + (minutes * 60) + seconds
        except ValueError:
            return None
        return None

    async def _notify_progress(self, progress_callback: Optional[Callable[[float], None]], progress: float):
        """Safely call a progress callback which may be sync or async."""
        if not progress_callback:
            return
        result = progress_callback(progress)
        if asyncio.iscoroutine(result):
            await result

    async def _notify_log(self, log_callback: Optional[Callable[[str], None]], message: str):
        """Safely call a log callback which may be sync or async."""
        if not log_callback:
            return
        result = log_callback(message)
        if asyncio.iscoroutine(result):
            await result

    async def _run_ffmpeg_with_progress(
        self,
        cmd: List[str],
        duration: float,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> tuple[int, bytes]:
        """Run ffmpeg and emit progress updates using -progress output."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as e:
            raise Exception(f"ffmpeg not found at {cmd[0]}") from e

        stderr_chunks: List[bytes] = []

        async def read_stderr():
            while True:
                chunk = await process.stderr.readline()
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        async def read_stdout():
            last_progress = -1.0
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()
                if not text or "=" not in text:
                    continue
                key, value = text.split("=", 1)
                seconds = self._parse_ffmpeg_time(key, value)
                if seconds is None or duration <= 0:
                    continue
                progress = min(100.0, (seconds / duration) * 100.0)
                if progress_callback and (progress - last_progress >= 0.5 or progress >= 100):
                    last_progress = progress
                    await self._notify_progress(progress_callback, progress)

        await asyncio.gather(read_stdout(), read_stderr())
        await process.wait()

        if process.returncode == 0:
            await self._notify_progress(progress_callback, 100.0)

        return process.returncode or 0, b"".join(stderr_chunks)

    async def transcode(
        self,
        input_path: str,
        output_format: OutputFormat,
        hw_accel: HardwareAccel = HardwareAccel.CPU,
        quality: str = "balanced",
        progress_callback: Optional[Callable[[float], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        remove_original: bool = False,
        remux_only: bool = False
    ) -> str:
        """
        Transcode a video file to a different format.

        Args:
            input_path: Path to input file
            output_format: Target format (mp4, mkv, ts)
            hw_accel: Hardware acceleration method
            quality: Quality preset (fast, balanced, quality)
            progress_callback: Optional callback for progress updates
            remove_original: Whether to delete the original file after transcoding

        Returns:
            Path to the transcoded file
        """
        if not self.ffmpeg_available:
            raise Exception("ffmpeg not found. Please install ffmpeg.")

        input_file = Path(input_path)
        output_path = input_file.with_suffix(f".{output_format.value}")

        # If same format and no transcoding needed, skip
        if input_file.suffix.lower() == f".{output_format.value}" and hw_accel == HardwareAccel.CPU:
            return str(input_path)

        # Build ffmpeg command
        cmd = [
            self._ffmpeg_path,
            "-i", str(input_path),
            "-y",  # Overwrite output
        ]

        if output_format in [OutputFormat.MP4, OutputFormat.MKV]:
            if remux_only:
                cmd.extend(["-map", "0", "-c", "copy"])
            else:
                # Add video encoder args
                cmd.extend(self._get_encoder_args(hw_accel, "h264", quality))
                # Audio - AAC for compatibility
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            # TS - copy streams
            cmd.extend(["-c", "copy"])

        cmd.extend([
            "-progress", "pipe:1",
            "-nostats",
            str(output_path)
        ])

        await self._notify_log(
            log_callback,
            f"ffmpeg cmd: {' '.join(str(c) for c in cmd)}"
        )

        # Run ffmpeg with progress
        duration = await self._get_duration(input_path)
        returncode, stderr = await self._run_ffmpeg_with_progress(cmd, duration, progress_callback)
        if returncode != 0:
            raise Exception(f"ffmpeg failed: {stderr.decode(errors='ignore')}")

        # Remove original if requested
        if remove_original and output_path.exists():
            os.remove(input_path)

        return str(output_path)

    async def detect_commercials(
        self,
        input_path: str,
        ini_path: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> Optional[str]:
        """
        Run Comskip to detect commercials and generate EDL file.

        Args:
            input_path: Path to video file
            ini_path: Optional path to comskip.ini config file

        Returns:
            Path to the EDL file, or None if no commercials detected
        """
        if not self.comskip_available:
            raise Exception("Comskip not found. Please install Comskip from https://github.com/erikkaashoek/Comskip")

        input_file = Path(input_path)
        output_dir = input_file.parent

        cmd = [self._comskip_path]

        if ini_path and os.path.isfile(ini_path):
            cmd.extend(["--ini", ini_path])

        cmd.extend([
            "--output", str(output_dir),
            str(input_path)
        ])

        await self._notify_log(
            log_callback,
            f"comskip cmd: {' '.join(str(c) for c in cmd)}"
        )

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        await process.communicate()

        # Check for EDL file (Edit Decision List)
        edl_path = input_file.with_suffix(".edl")
        if edl_path.exists():
            return str(edl_path)

        return None

    async def remove_commercials(
        self,
        input_path: str,
        edl_path: str,
        output_format: OutputFormat = OutputFormat.MP4,
        hw_accel: HardwareAccel = HardwareAccel.CPU,
        remove_original: bool = False,
        progress_callback: Optional[Callable[[float], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        remux_only: bool = False
    ) -> str:
        """
        Remove commercials from video using EDL file.

        Args:
            input_path: Path to video file
            edl_path: Path to EDL file from Comskip
            output_format: Output format
            hw_accel: Hardware acceleration method
            remove_original: Whether to delete original after processing

        Returns:
            Path to the commercial-free video
        """
        if not self.ffmpeg_available:
            raise Exception("ffmpeg not found. Please install ffmpeg.")

        # Parse EDL file to get commercial segments
        segments = self._parse_edl(edl_path)

        if not segments:
            # No commercials, just transcode if needed
            return await self.transcode(
                input_path,
                output_format,
                hw_accel,
                progress_callback=progress_callback,
                log_callback=log_callback,
                remove_original=remove_original,
                remux_only=remux_only
            )

        input_file = Path(input_path)
        output_path = input_file.with_stem(f"{input_file.stem}_clean").with_suffix(f".{output_format.value}")

        # Get video duration
        duration = await self._get_duration(input_path)

        # Build keep segments (inverse of commercial segments)
        keep_segments = self._invert_segments(segments, duration)

        if not keep_segments:
            return await self.transcode(
                input_path,
                output_format,
                hw_accel,
                progress_callback=progress_callback,
                log_callback=log_callback,
                remove_original=remove_original,
                remux_only=remux_only
            )

        # Create concat file for ffmpeg
        concat_file = input_file.with_suffix(".concat.txt")
        temp_files = []

        try:
            await self._notify_log(
                log_callback,
                f"Commercial removal: extracting {len(keep_segments)} keep segments with ffmpeg copy."
            )
            # Extract each segment
            segment_count = len(keep_segments)
            for i, (start, end) in enumerate(keep_segments):
                temp_path = input_file.with_stem(f"{input_file.stem}_seg{i}").with_suffix(".ts")
                temp_files.append(temp_path)

                cmd = [
                    self._ffmpeg_path,
                    "-i", str(input_path),
                    "-ss", str(start),
                    "-to", str(end),
                    "-c", "copy",
                    "-y",
                    str(temp_path)
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                if progress_callback and segment_count > 0:
                    await self._notify_progress(progress_callback, (i + 1) / segment_count * 40.0)

            # Write concat file
            with open(concat_file, "w") as f:
                for temp_path in temp_files:
                    f.write(f"file '{temp_path}'\n")

            # Concat and encode
            cmd = [
                self._ffmpeg_path,
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
            ]

            if output_format in [OutputFormat.MP4, OutputFormat.MKV]:
                cmd.extend(self._get_encoder_args(hw_accel))
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                cmd.extend(["-c", "copy"])

            cmd.extend(["-progress", "pipe:1", "-nostats", "-y", str(output_path)])

            kept_duration = sum(end - start for start, end in keep_segments)
            async def mapped_callback(p: float):
                await self._notify_progress(progress_callback, 40.0 + (p * 0.6))
            await self._notify_log(
                log_callback,
                f"ffmpeg concat cmd: {' '.join(str(c) for c in cmd)}"
            )
            returncode, stderr = await self._run_ffmpeg_with_progress(
                cmd,
                kept_duration,
                progress_callback=mapped_callback if progress_callback else None
            )

            if returncode != 0:
                raise Exception(f"ffmpeg concat failed: {stderr.decode(errors='ignore')}")

        finally:
            # Cleanup temp files
            for temp_path in temp_files:
                if temp_path.exists():
                    os.remove(temp_path)
            if concat_file.exists():
                os.remove(concat_file)

        if remove_original:
            os.remove(input_path)

        return str(output_path)

    def _parse_edl(self, edl_path: str) -> list:
        """Parse EDL file and return list of (start, end, type) tuples."""
        segments = []
        with open(edl_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    start = float(parts[0])
                    end = float(parts[1])
                    seg_type = int(parts[2])
                    # Type 0 = cut, 3 = commercial
                    if seg_type in [0, 3]:
                        segments.append((start, end, seg_type))
        return segments

    def _invert_segments(self, commercial_segments: list, duration: float) -> list:
        """Convert commercial segments to keep segments."""
        if not commercial_segments:
            return [(0, duration)]

        keep_segments = []
        current_pos = 0

        for start, end, _ in sorted(commercial_segments):
            if start > current_pos:
                keep_segments.append((current_pos, start))
            current_pos = end

        if current_pos < duration:
            keep_segments.append((current_pos, duration))

        return keep_segments

    async def _get_duration(self, input_path: str) -> float:
        """Get video duration using ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            ffprobe = self._ffmpeg_path.replace("ffmpeg", "ffprobe") if self._ffmpeg_path else None

        if not ffprobe:
            return 0

        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, _ = await process.communicate()
        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 0


# Global instance
post_processor = PostProcessor()
