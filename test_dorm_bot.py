"""
test_dorm_bot.py
================
Automated test suite verifying all 11 core requirements:
1. Photo blur and validity.
2. Video blurred across multiple frames throughout.
3. Video with audio track.
4. Video without audio track.
5. Corrupted photo rejected without publishing original.
6. Corrupted video rejected without publishing original.
7. Simulated failure does not trigger original-media fallback.
8. Temporary files cleaned up in both success and failure cases.
9. Description and /skip flows work.
10. Rate limiting and text reports work.
11. Every photo/video publication path sends only processed output.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

# Set dummy environment variables BEFORE importing bot/media_processor
os.environ.setdefault("BOT_TOKEN", "123456789:AA_dummy_test_token_never_sent")
os.environ.setdefault("CHANNEL_ID", "-1009999999999")

import bot
import media_processor
from media_processor import (
    blur_photo,
    blur_video,
    get_ffmpeg_binary,
    process_and_publish_media,
    validate_photo,
    validate_video,
)


@pytest.fixture(scope="session")
def ffmpeg_bin():
    return get_ffmpeg_binary()


# ── Requirement 1: Photo is blurred and output is a valid image ───────────────

def test_photo_blurred_and_valid(tmp_path):
    img_path = str(tmp_path / "test_photo.jpg")
    out_path = str(tmp_path / "blurred_photo.jpg")

    # Create a sharp image with high-contrast text and geometric patterns
    img = Image.new("RGB", (600, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, 550, 350], fill=(0, 0, 0))
    draw.text((100, 150), "STUDENT DORM SECRET REPORT #12345", fill=(255, 255, 255))
    img.save(img_path, format="JPEG")

    blur_photo(img_path, out_path)

    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 100

    # Validate output image
    validate_photo(out_path)
    with Image.open(out_path) as out_img:
        assert out_img.size == (600, 400)
        out_arr = np.array(out_img)

    orig_arr = np.array(img)
    # The sharp black-white transition should be smoothed significantly
    diff = np.abs(orig_arr.astype(float) - out_arr.astype(float)).mean()
    assert diff > 15.0, f"Expected strong blur difference, got mean diff of {diff}"


# ── Requirement 2: Video blurred throughout multiple frames ───────────────────

def test_video_multiple_frames_blurred_throughout(tmp_path, ffmpeg_bin):
    input_video = str(tmp_path / "test_multiframe.mp4")
    output_video = str(tmp_path / "blurred_multiframe.mp4")

    # Generate a 3-second test video at 24fps (72 frames) with moving patterns and text
    cmd_gen = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=480x320:rate=24",
        "-c:v", "libx264",
        input_video
    ]
    subprocess.run(cmd_gen, check=True, capture_output=True)

    blur_video(input_video, output_video)
    validate_video(output_video)

    # Extract frames at t=0.5s, 1.5s, 2.5s and check blur across all of them
    for ts in [0.5, 1.5, 2.5]:
        orig_frame = str(tmp_path / f"orig_f_{ts}.png")
        blur_frame = str(tmp_path / f"blur_f_{ts}.png")

        subprocess.run([ffmpeg_bin, "-y", "-ss", str(ts), "-i", input_video, "-vframes", "1", orig_frame], check=True, capture_output=True)
        subprocess.run([ffmpeg_bin, "-y", "-ss", str(ts), "-i", output_video, "-vframes", "1", blur_frame], check=True, capture_output=True)

        orig_arr = np.array(Image.open(orig_frame)).astype(float)
        blur_arr = np.array(Image.open(blur_frame)).astype(float)

        diff = np.abs(orig_arr - blur_arr).mean()
        assert diff > 10.0, f"Frame at {ts}s did not exhibit strong blur (mean diff: {diff})"


# ── Requirement 3: Video with audio handled correctly ─────────────────────────

def test_video_with_audio_handled_correctly(tmp_path, ffmpeg_bin):
    input_video = str(tmp_path / "with_audio.mp4")
    output_video = str(tmp_path / "blurred_audio.mp4")

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=20",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-c:a", "aac",
        input_video
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    blur_video(input_video, output_video)
    validate_video(output_video)

    # Check streams: must have at least 1 video and 1 audio stream
    probe = subprocess.run([
        ffmpeg_bin, "-i", output_video
    ], capture_output=True, text=True)

    assert "Video:" in probe.stderr
    assert "Audio:" in probe.stderr


# ── Requirement 4: Video without audio handled correctly ──────────────────────

def test_video_without_audio_handled_correctly(tmp_path, ffmpeg_bin):
    input_video = str(tmp_path / "no_audio.mp4")
    output_video = str(tmp_path / "blurred_no_audio.mp4")

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=20",
        "-c:v", "libx264",
        input_video
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    blur_video(input_video, output_video)
    validate_video(output_video)

    probe = subprocess.run([
        ffmpeg_bin, "-i", output_video
    ], capture_output=True, text=True)

    assert "Video:" in probe.stderr
    assert "Audio:" not in probe.stderr


# ── Requirement 5: Corrupted photo rejected without publishing original ───────

def test_corrupted_photo_rejected(tmp_path):
    async def run():
        mock_bot = AsyncMock()

        corrupt_file = str(tmp_path / "corrupt.jpg")
        with open(corrupt_file, "wb") as f:
            f.write(b"NOT_A_VALID_JPEG_HEADER_1234567890")

        async def fake_download(file, destination):
            shutil.copyfile(corrupt_file, destination)

        mock_bot.download.side_effect = fake_download

        with pytest.raises(Exception):
            await process_and_publish_media(
                bot=mock_bot,
                channel_id="-100123",
                media_type="photo",
                file_id="bad_file_id",
                caption="test",
            )

        # Verify original was NEVER published
        assert mock_bot.send_photo.call_count == 0
        assert mock_bot.copy_message.call_count == 0

    asyncio.run(run())


# ── Requirement 6: Corrupted video rejected without publishing original ───────

def test_corrupted_video_rejected(tmp_path):
    async def run():
        mock_bot = AsyncMock()

        corrupt_video = str(tmp_path / "corrupt.mp4")
        with open(corrupt_video, "wb") as f:
            f.write(b"CORRUPT_VIDEO_BINARY_DATA_GARBAGE")

        async def fake_download(file, destination):
            shutil.copyfile(corrupt_video, destination)

        mock_bot.download.side_effect = fake_download

        with pytest.raises(Exception):
            await process_and_publish_media(
                bot=mock_bot,
                channel_id="-100123",
                media_type="video",
                file_id="bad_video_id",
                caption="test",
            )

        assert mock_bot.send_video.call_count == 0
        assert mock_bot.copy_message.call_count == 0

    asyncio.run(run())


# ── Requirement 7: Simulated failure does not trigger fallback ────────────────

def test_simulated_processing_failure_no_fallback(tmp_path):
    async def run():
        mock_bot = AsyncMock()

        sample_img = str(tmp_path / "valid_sim.jpg")
        img = Image.new("RGB", (100, 100), color=(50, 50, 50))
        img.save(sample_img)

        async def fake_download(file, destination):
            shutil.copyfile(sample_img, destination)

        mock_bot.download.side_effect = fake_download

        with patch("media_processor.blur_photo", side_effect=RuntimeError("Simulated disk error")):
            with pytest.raises(RuntimeError):
                await process_and_publish_media(
                    bot=mock_bot,
                    channel_id="-100123",
                    media_type="photo",
                    file_id="file123",
                    caption="caption",
                )

        # Must NEVER fall back to copy_message or send_message with original media
        assert mock_bot.copy_message.call_count == 0
        assert mock_bot.send_photo.call_count == 0

    asyncio.run(run())


# ── Requirement 8: Temporary files cleaned up in success and failure ──────────

def test_temporary_files_cleaned_up_success_and_failure(tmp_path):
    async def run():
        mock_bot = AsyncMock()

        # Create valid sample image
        sample_img = str(tmp_path / "valid.jpg")
        img = Image.new("RGB", (200, 200), color=(100, 150, 200))
        img.save(sample_img)

        tracked_files = []
        original_named_temp = tempfile.NamedTemporaryFile

        def tracking_tempfile(*args, **kwargs):
            tf = original_named_temp(*args, **kwargs)
            tracked_files.append(tf.name)
            return tf

        # Case A: Success cleanup
        async def fake_download_ok(file, destination):
            shutil.copyfile(sample_img, destination)

        mock_bot.download.side_effect = fake_download_ok

        with patch("media_processor.tempfile.NamedTemporaryFile", side_effect=tracking_tempfile):
            await process_and_publish_media(
                bot=mock_bot,
                channel_id="-100123",
                media_type="photo",
                file_id="ok_id",
                caption="ok",
            )

        for tf_name in tracked_files:
            assert not os.path.exists(tf_name), f"Temp file {tf_name} was not deleted after success"

        # Case B: Failure cleanup
        tracked_files.clear()
        with patch("media_processor.tempfile.NamedTemporaryFile", side_effect=tracking_tempfile):
            with patch("media_processor.blur_photo", side_effect=RuntimeError("Forced failure")):
                with pytest.raises(RuntimeError):
                    await process_and_publish_media(
                        bot=mock_bot,
                        channel_id="-100123",
                        media_type="photo",
                        file_id="fail_id",
                        caption="fail",
                    )

        for tf_name in tracked_files:
            assert not os.path.exists(tf_name), f"Temp file {tf_name} was not deleted after failure"

    asyncio.run(run())


# ── Requirement 9 & 11: Description and /skip flows work & send only blurred ──

def test_description_and_skip_flows():
    async def run():
        # Test desc_skip
        mock_message = AsyncMock()
        mock_state = AsyncMock()
        mock_state.get_data.return_value = {
            "media_type": "photo",
            "file_id": "photo_123",
            "src_chat": 12345,
            "src_msg": 67890,
        }

        with patch("bot.process_and_publish_media", new_callable=AsyncMock) as mock_pub:
            await bot.desc_skip(mock_message, mock_state)
            mock_pub.assert_called_once_with(
                bot.bot, bot.CHANNEL_ID, "photo", "photo_123", bot.HEADER.strip()
            )
            mock_message.answer.assert_called_once_with("✅ Your report was posted anonymously. Thank you!")
            mock_state.clear.assert_called_once()

        # Test desc_received
        mock_message.reset_mock()
        mock_state.reset_mock()
        mock_message.text = "Water leak in Room 302"

        with patch("bot.process_and_publish_media", new_callable=AsyncMock) as mock_pub:
            await bot.desc_received(mock_message, mock_state)
            expected_caption = f"{bot.HEADER}Water leak in Room 302"
            mock_pub.assert_called_once_with(
                bot.bot, bot.CHANNEL_ID, "photo", "photo_123", expected_caption
            )
            mock_message.answer.assert_called_once_with("✅ Your report was posted anonymously. Thank you!")
            mock_state.clear.assert_called_once()

        # Test error handling on failure: sender notified, no original publish
        mock_message.reset_mock()
        mock_state.reset_mock()
        with patch("bot.process_and_publish_media", side_effect=RuntimeError("Process error")):
            await bot.desc_skip(mock_message, mock_state)
            mock_message.answer.assert_called_once_with(bot.FAIL_SAFE_ERROR)
            mock_state.clear.assert_called_once()

    asyncio.run(run())


# ── Requirement 10: Rate limit and text reports work ───────────────────────────

def test_rate_limit_and_text_report():
    async def run():
        bot._last_seen.clear()

        user_id = 99999
        # First submission allowed
        assert bot._rate_limited(user_id) is None

        # Immediate second submission blocked with remaining seconds
        remaining = bot._rate_limited(user_id)
        assert remaining is not None
        assert 1 <= remaining <= bot.RATE_LIMIT + 1

        # Text report handler
        mock_msg = AsyncMock()
        mock_msg.from_user.id = 88888
        mock_msg.text = "Cafeteria was closed early"

        with patch.object(bot.bot, "send_message", new_callable=AsyncMock) as mock_send:
            await bot.handle_text(mock_msg)
            expected_text = f"{bot.HEADER}Cafeteria was closed early"
            mock_send.assert_called_once_with(
                chat_id=bot.CHANNEL_ID, text=expected_text, parse_mode="HTML"
            )
            mock_msg.answer.assert_called_once_with(
                "✅ Your report was posted anonymously. Thank you for helping improve our dorm!"
            )

    asyncio.run(run())


# ── Requirement 11: handle_media path routing ─────────────────────────────────

def test_handle_media_routing():
    async def run():
        bot._last_seen.clear()

        # Photo with existing caption
        mock_msg = AsyncMock()
        mock_msg.from_user.id = 77777
        mock_msg.media_group_id = None
        mock_msg.photo = [MagicMock(file_id="p1"), MagicMock(file_id="p2")]
        mock_msg.video = None
        mock_msg.document = None
        mock_msg.caption = "Broken faucet"
        mock_state = AsyncMock()

        with patch("bot.process_and_publish_media", new_callable=AsyncMock) as mock_pub:
            with patch("bot._copy_to_channel", new_callable=AsyncMock) as mock_copy:
                await bot.handle_media(mock_msg, mock_state)
                mock_pub.assert_called_once_with(
                    bot.bot, bot.CHANNEL_ID, "photo", "p2", f"{bot.HEADER}Broken faucet"
                )
                # NEVER copy directly
                mock_copy.assert_not_called()

        # Document (preserved handling without blur)
        bot._last_seen.clear()
        mock_msg.reset_mock()
        mock_msg.from_user.id = 77777
        mock_msg.media_group_id = None
        mock_msg.photo = None
        mock_msg.video = None
        mock_msg.document = MagicMock(file_id="doc1")
        mock_msg.caption = "Rules PDF"
        mock_msg.chat.id = 11111
        mock_msg.message_id = 22222

        with patch("bot.process_and_publish_media", new_callable=AsyncMock) as mock_pub:
            with patch("bot._copy_to_channel", new_callable=AsyncMock) as mock_copy:
                await bot.handle_media(mock_msg, mock_state)
                mock_pub.assert_not_called()
                mock_copy.assert_called_once_with(11111, 22222, f"{bot.HEADER}Rules PDF")

    asyncio.run(run())
