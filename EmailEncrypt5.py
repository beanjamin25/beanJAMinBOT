"""
S/MIME Email Encryption by shelling out to the openssl CLI

Approach: no Python crypto library at all for the CMS step. We hand the
plaintext to `openssl smime -encrypt` over stdin and read the SMIME-formatted
output from stdout. The only Python crypto involvement is whatever cryptography
or stdlib code you use elsewhere.

Why this is sometimes the right answer:
    - The openssl binary is essentially guaranteed on RHEL/UBI hosts and CI.
    - Zero new Python dependencies, zero ASN.1 code to audit.
    - Behaviour matches whatever the system openssl does, so debugging
      "Outlook can't decrypt this" is a `openssl smime -decrypt` away.

Tradeoffs:
    - Subprocess overhead per message (~tens of ms).
    - Cert path must be accessible to the openssl process.
    - You inherit the system openssl's defaults and bugs.

Requirements:
    The `openssl` binary on PATH. No Python deps beyond the stdlib.
"""

import shutil
import smtplib
import subprocess
from email.mime.text import MIMEText


class OpenSSLNotFoundError(RuntimeError):
    """Raised when the openssl binary is not available on PATH."""


class SMIMEEncryptionError(RuntimeError):
    """Raised when openssl exits non-zero during encryption."""


def _require_openssl() -> str:
    path = shutil.which('openssl')
    if path is None:
        raise OpenSSLNotFoundError("openssl binary not found on PATH")
    return path


def encrypt_smime(plaintext: bytes, recipient_cert_path: str, cipher: str = '-aes-256-cbc') -> bytes:
    """Encrypt plaintext into an SMIME-formatted blob via the openssl CLI."""
    openssl = _require_openssl()
    proc = subprocess.run(
        [openssl, 'smime', '-encrypt', cipher, '-outform', 'SMIME', recipient_cert_path],
        input=plaintext,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SMIMEEncryptionError(
            f"openssl smime -encrypt failed (rc={proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return proc.stdout


class SMIMEMailer:
    """S/MIME encrypted email sender backed by the openssl CLI."""

    def __init__(self, smtp_host, smtp_port=587, username=None, password=None, use_tls=True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def create_encrypted_email(self, from_addr, to_addr, subject, body, recipient_cert_path) -> bytes:
        # Build the inner MIME message exactly as the other implementations do
        inner = MIMEText(body, 'plain', 'utf-8').as_string()
        smime_blob = encrypt_smime(inner.encode('utf-8'), recipient_cert_path)

        # openssl emits a full SMIME message body but without the routing
        # headers. Prepend them so SMTP and recipient clients route correctly.
        headers = (
            f"From: {from_addr}\r\n"
            f"To: {to_addr}\r\n"
            f"Subject: {subject}\r\n"
        ).encode('utf-8')
        return headers + smime_blob

    def send_encrypted(self, from_addr, to_addr, subject, body, recipient_cert_path) -> None:
        payload = self.create_encrypted_email(from_addr, to_addr, subject, body, recipient_cert_path)
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(from_addr, to_addr, payload)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="S/MIME encrypted email via openssl CLI")
    parser.add_argument("--smtp-host", required=True)
    parser.add_argument("--smtp-port", type=int, default=587)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--from", dest="from_addr", required=True)
    parser.add_argument("--to", dest="to_addr", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--cert", required=True)
    args = parser.parse_args()

    SMIMEMailer(
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        username=args.username,
        password=args.password,
    ).send_encrypted(
        from_addr=args.from_addr,
        to_addr=args.to_addr,
        subject=args.subject,
        body=args.body,
        recipient_cert_path=args.cert,
    )
    print(f"Encrypted email sent to {args.to_addr}")
