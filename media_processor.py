"""
media_processor.py
==================
Media processing module for blurring photos and videos before publishing.
Ensures fail-safe privacy: original unblurred media is NEVER published.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from PIL import Image, ImageFilter, ImageOps
from aiogram import Bot
from aiogram.types import FSInputFile

log = logging.getLogger("anon_dorm_bot.media_processor")


def get_ffmpeg_binary() -> str:
    """Find ffmpeg binary from PATH or imageio_ffmpeg if installed."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def blur_photo(input_path: str, output_path: str) -> None:
    """
    Apply a strong, uniform blur to an image.
    Preserves basic dimensions and EXIF orientation.
    Validates output before completing.
    """
    if not os.path.exists(input_path) or os.path.getsize(input_path) < 10:
        raise ValueError("Input photo file is missing or empty")

    try:
        with Image.open(input_path) as img:
            # Respect orientation from camera EXIF
            img = ImageOps.exif_transpose(img)

            # Ensure image is in RGB or RGBA mode
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            w, h = img.size
            if w <= 0 or h <= 0:
                raise ValueError(f"Invalid image dimensions: {w}x{h}")

            # Compute strong blur radius proportional to image dimensions (minimum 25px)
            min_dim = min(w, h)
            radius = max(25, int(min_dim * 0.05))

            blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))

            # Save blurred image
            if img.mode == "RGBA":
                blurred.save(output_path, format="PNG")
            else:
                blurred.save(output_path, format="JPEG", quality=90)

        # Validate the generated output
        validate_photo(output_path)

    except Exception as exc:
        log.error("Photo blur processing failed: %s", type(exc).__name__)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        raise


def blur_video(input_path: str, output_path: str) -> None:
    """
    Apply a strong, uniform blur to every frame of a video using FFmpeg.
    Handles videos with or without audio tracks.
    Preserves dimensions, orientation, and playback compatibility.
    Validates output before completing.
    """
    if not os.path.exists(input_path) or os.path.getsize(input_path) < 100:
        raise ValueError("Input video file is missing or empty")

    ffmpeg_exe = get_ffmpeg_binary()

    # Filter: boxblur with radius proportional to dimensions (min 15px) and 2 power passes
    filter_str = (
        "boxblur=luma_radius=max(15\\,min(w\\,h)/25):luma_power=2:"
        "chroma_radius=max(15\\,min(cw\\,ch)/25):chroma_power=2"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:a", "aac",
        output_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            log.error("FFmpeg video blur returned non-zero exit code: %d", proc.returncode)
            raise RuntimeError(f"FFmpeg processing failed with code {proc.returncode}")

        # Validate generated output
        validate_video(output_path)

    except Exception as exc:
        log.error("Video blur processing failed: %s", type(exc).__name__)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        raise


def validate_photo(path: str) -> None:
    """Validate that photo output exists and is a readable, non-empty image."""
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        raise ValueError("Photo file is missing or too small")
    with Image.open(path) as img:
        img.verify()
    with Image.open(path) as img:
        img.load()


def validate_video(path: str) -> None:
    """Validate that video output exists and can be decoded by FFmpeg."""
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        raise ValueError("Video file is missing or too small")

    ffmpeg_exe = get_ffmpeg_binary()
    check_cmd = [
        ffmpeg_exe,
        "-v", "error",
        "-i", path,
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(check_cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        log.error("Video validation failed: %s", proc.stderr.strip())
        raise ValueError(f"Processed video is invalid or corrupted: {proc.stderr.strip()}")


async def process_and_publish_media(
    bot: Bot,
    channel_id: str,
    media_type: str,
    file_id: str,
    caption: str,
) -> None:
    """
    Download submitted media, blur every frame/image, validate output,
    and publish ONLY the blurred version.
    Ensures fail-safe cleanup of all temporary files.
    Original unblurred media is NEVER sent to the channel.
    """
    temp_in = None
    temp_out = None

    try:
        suffix = ".jpg" if media_type == "photo" else ".mp4"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_in:
            temp_in = f_in.name
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f_out:
            temp_out = f_out.name

        # 1. Download original media to temp_in
        await bot.download(file=file_id, destination=temp_in)

        if not os.path.exists(temp_in) or os.path.getsize(temp_in) == 0:
            raise ValueError(f"Downloaded {media_type} is empty or missing")

        # 2. Apply strong blur and validate
        if media_type == "photo":
            blur_photo(temp_in, temp_out)
            # 3. Publish blurred photo ONLY
            await bot.send_photo(
                chat_id=channel_id,
                photo=FSInputFile(temp_out),
                caption=caption,
                parse_mode="HTML",
            )
        elif media_type == "video":
            blur_video(temp_in, temp_out)
            # 3. Publish blurred video ONLY
            await bot.send_video(
                chat_id=channel_id,
                video=FSInputFile(temp_out),
                caption=caption,
                parse_mode="HTML",
            )
        else:
            raise ValueError(f"Unsupported media type for blur: {media_type}")

    finally:
        # 4. Guarantee deletion of both temporary files
        for p in (temp_in, temp_out):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError as err:
                    log.warning("Could not delete temporary file %s: %s", p, err)
