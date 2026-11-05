"""Runtime-only public CA integration; never embed a builder's private trust."""
from contextlib import contextmanager
import os
from pathlib import Path
import ssl
import tempfile


@contextmanager
def trust_environment(base=None, additional=None):
    base = Path(base or os.environ.get("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"))
    additional = additional or ("/etc/ssl/certs/additional-ca.pem" if os.environ.get("AUDIOBOOK_HAS_EXTRA_CA") == "1" else None)
    ssl.create_default_context(cafile=str(base))
    if additional is None:
        yield
        return
    additional = Path(additional)
    # Validate certificates; failures are not converted to an insecure fallback.
    ssl.create_default_context(cafile=str(additional))
    previous = os.environ.get("SSL_CERT_FILE")
    with tempfile.TemporaryDirectory(prefix="audiobook-ca-") as directory:
        merged = Path(directory) / "roots.pem"
        merged.write_bytes(base.read_bytes() + b"\n" + additional.read_bytes() + b"\n")
        merged.chmod(0o600)
        os.environ["SSL_CERT_FILE"] = str(merged)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = previous
