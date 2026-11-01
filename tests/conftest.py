import subprocess

import pytest


@pytest.fixture
def audio(tmp_path):
    def create(name="chapter 1.mp3", duration=0.5, rate=44100, frequency=440):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"sine=frequency={frequency}:duration={duration}:sample_rate={rate}",
                        "-metadata", "title=Synthetic chapter", str(path)], check=True)
        return path
    return create


@pytest.fixture
def artwork():
    import io
    from PIL import Image
    def make(color="red", format="PNG"):
        stream = io.BytesIO()
        Image.new("RGB", (64, 96), color).save(stream, format=format)
        return stream.getvalue()
    return make
