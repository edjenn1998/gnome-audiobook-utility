import subprocess

import pytest


@pytest.fixture(scope="session")
def native_app():
    pytest.importorskip("gi")
    from audiobook_utility.ui import Application, Gio
    app = Application()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    assert app.register()
    yield app
    app.quit()


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


@pytest.fixture
def encrypted_aaxc(audio, artwork, tmp_path):
    """Synthetic AAC packets encrypted as AAXC: per-packet AES-CBC, clear tail bytes."""
    import json
    import threading

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    from audiobook_utility.media import merge

    reference = tmp_path / "reference.m4b"
    merge([audio("first.wav", duration=0.6), audio("second.wav", duration=0.7)],
          reference, threading.Event(), titles=["Opening", "Ending"],
          tags={"title": "Synthetic audiobook", "artist": "Test author", "narrator": "Test voice"},
          artwork=artwork())
    packets = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets",
        "-show_entries", "packet=pos,size", "-of", "json", str(reference),
    ]))["packets"]
    # These deterministic keys protect generated test tones, not purchased content.
    voucher = {"key": "0123456789abcdef0123456789abcdef", "iv": "fedcba9876543210fedcba9876543210"}
    content = bytearray(reference.read_bytes())
    assert content[4:8] == b"ftyp"
    content[8:12] = b"aaxc"
    for packet in packets:
        offset = int(packet["pos"])
        length = int(packet["size"]) // 16 * 16
        encryptor = Cipher(algorithms.AES(bytes.fromhex(voucher["key"])),
                           modes.CBC(bytes.fromhex(voucher["iv"]))).encryptor()
        content[offset:offset + length] = (
            encryptor.update(bytes(content[offset:offset + length])) + encryptor.finalize())
    source = tmp_path / "Synthetic [B000000001].aaxc"
    source.write_bytes(content)
    return source, reference, voucher
