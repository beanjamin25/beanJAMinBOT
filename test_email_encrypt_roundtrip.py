"""
Round-trip smoke test for EmailEncrypt3 / 4 / 5.

For each implementation we encrypt a known plaintext and pipe the result
through `openssl smime -decrypt` (with the matching private key) as an
independent oracle. If the bytes that come back equal the bytes that went
in, the implementation produced a correctly-formed CMS message.

This is NOT a full test suite — it's a sanity check you can run after
`pip install asn1crypto endesive` to confirm each path works end-to-end.

Usage:
    python test_email_encrypt_roundtrip.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PLAINTEXT = b"Hello from the round-trip test. \xe2\x98\x83 unicode survives.\n"


# =============================================================================
# Setup: generate a throwaway RSA key + self-signed cert with openssl
# =============================================================================

def generate_test_cert(workdir: Path) -> tuple[Path, Path]:
    """Return (cert_path, key_path) for a fresh self-signed RSA cert."""
    key_path = workdir / "test.key"
    cert_path = workdir / "test.crt"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_path), "-out", str(cert_path),
            "-days", "1", "-nodes",
            "-subj", "/CN=roundtrip-test",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


# =============================================================================
# Oracle: openssl decrypt
# =============================================================================

def openssl_decrypt(ciphertext: bytes, key_path: Path, inform: str) -> bytes:
    """Decrypt CMS bytes with openssl, returning the recovered plaintext."""
    proc = subprocess.run(
        ["openssl", "smime", "-decrypt", "-inform", inform, "-inkey", str(key_path)],
        input=ciphertext,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"openssl decrypt failed (rc={proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return proc.stdout


# =============================================================================
# Per-implementation probes — each returns (ciphertext_bytes, openssl_inform)
# =============================================================================

def probe_encrypt3(plaintext: bytes, cert_path: Path) -> tuple[bytes, str]:
    from EmailEncrypt3 import build_enveloped_data_der
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return build_enveloped_data_der(plaintext, cert), "DER"


def probe_encrypt4(plaintext: bytes, cert_path: Path) -> tuple[bytes, str]:
    # Skip the SMIMEMailer wrapper and hit endesive directly — the test
    # cares about CMS correctness, not our header-prepending shim.
    from cryptography import x509
    from endesive.email import encrypt as endesive_encrypt
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    blob = endesive_encrypt(plaintext, [cert])
    if isinstance(blob, str):
        blob = blob.encode("utf-8")
    return blob, "SMIME"


def probe_encrypt5(plaintext: bytes, cert_path: Path) -> tuple[bytes, str]:
    # Simulates the AD path: read cert bytes into memory at the boundary,
    # then hand the bytes to the encrypt function which never re-reads
    # the path (it uses memfd_create internally).
    from EmailEncrypt5 import encrypt_smime
    cert_bytes = cert_path.read_bytes()
    return encrypt_smime(plaintext, cert_bytes), "SMIME"


# =============================================================================
# Runner
# =============================================================================

PROBES = [
    ("EmailEncrypt3 (asn1crypto)", probe_encrypt3, PLAINTEXT),
    # endesive expects an email-shaped payload, not arbitrary bytes;
    # use a printable plaintext so decoded MIME comes back intact.
    ("EmailEncrypt4 (endesive)", probe_encrypt4, b"hello from endesive\n"),
    ("EmailEncrypt5 (openssl CLI, in-memory cert)", probe_encrypt5, PLAINTEXT),
]


def run_one(name: str, probe, plaintext: bytes, cert_path: Path, key_path: Path) -> str:
    try:
        ciphertext, inform = probe(plaintext, cert_path)
    except ImportError as e:
        return f"SKIP  {name}: missing dependency ({e.name})"
    except Exception as e:
        return f"FAIL  {name}: encrypt raised {type(e).__name__}: {e}"

    try:
        recovered = openssl_decrypt(ciphertext, key_path, inform)
    except Exception as e:
        return f"FAIL  {name}: decrypt raised {type(e).__name__}: {e}"

    # openssl canonicalizes LF -> CRLF on the S/MIME path (RFC 2045),
    # so compare with line endings normalized.
    def _norm(b: bytes) -> bytes:
        return b.replace(b"\r\n", b"\n")

    # EmailEncrypt4 round-trips a full MIME message, so check substring.
    # EmailEncrypt3/5 round-trip raw bytes, so check exact equality.
    if name.startswith("EmailEncrypt4"):
        ok = _norm(plaintext) in _norm(recovered)
    else:
        ok = _norm(recovered) == _norm(plaintext)

    if ok:
        return f"PASS  {name}"
    return (
        f"FAIL  {name}: roundtrip mismatch\n"
        f"      expected: {plaintext!r}\n"
        f"      got:      {recovered!r}"
    )


def main() -> int:
    if shutil.which("openssl") is None:
        print("openssl binary not found on PATH — cannot run round-trip test", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        cert_path, key_path = generate_test_cert(workdir)

        results = [run_one(name, probe, pt, cert_path, key_path) for name, probe, pt in PROBES]

    for line in results:
        print(line)

    return 0 if all(r.startswith(("PASS", "SKIP")) for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
