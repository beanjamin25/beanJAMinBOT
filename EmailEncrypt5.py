"""
S/MIME Email Encryption by shelling out to the openssl CLI (in-memory cert)

Approach: no Python crypto library at all for the CMS step. We hand the
plaintext to `openssl smime -encrypt` over stdin and read the SMIME-formatted
output from stdout. The recipient cert is held only in an anonymous
memfd_create() file descriptor and exposed to openssl as /dev/fd/N — it
never touches the filesystem.

Designed for workflows where the cert is fetched at runtime (e.g. from
Active Directory) and writing it to disk would violate policy.

Why this is sometimes the right answer:
    - The openssl binary is essentially guaranteed on RHEL/UBI hosts and CI.
    - Zero new Python dependencies, zero ASN.1 code to audit.
    - Behaviour matches whatever the system openssl does, so debugging
      "Outlook can't decrypt this" is a `openssl smime -decrypt` away.

Tradeoffs:
    - Subprocess overhead per message (~tens of ms).
    - You inherit the system openssl's defaults and bugs.
    - Linux only (memfd_create is a Linux syscall).

Requirements:
    The `openssl` binary on PATH. Linux + Python 3.8+ (for os.memfd_create).
    No Python deps beyond the stdlib.
"""

# pattern: Imperative Shell

import os
import shutil
import smtplib
import subprocess
from email.mime.text import MIMEText


class OpenSSLNotFoundError(RuntimeError):
    """Raised when the openssl binary is not available on PATH."""


class MemfdUnavailableError(RuntimeError):
    """Raised when os.memfd_create is not available (non-Linux platforms)."""


class SMIMEEncryptionError(RuntimeError):
    """Raised when openssl exits non-zero during encryption."""


def _require_openssl() -> str:
    path = shutil.which('openssl')
    if path is None:
        raise OpenSSLNotFoundError("openssl binary not found on PATH")
    return path


def _require_memfd() -> None:
    if not hasattr(os, 'memfd_create'):
        raise MemfdUnavailableError(
            "os.memfd_create unavailable on this platform; "
            "in-memory cert encryption requires Linux + Python 3.8+"
        )


def encrypt_smime(plaintext: bytes, cert_data: bytes, cipher: str = '-aes-256-cbc') -> bytes:
    """Encrypt plaintext to SMIME via openssl, with cert held only in memory.

    The cert bytes are written to an anonymous memfd_create() file descriptor
    and exposed to openssl as /dev/fd/N. The cert never touches the filesystem;
    the fd is closed in a finally block and the kernel reclaims the memory.
    """
    openssl = _require_openssl()
    _require_memfd()
    if not cert_data:
        raise SMIMEEncryptionError("cert_data is empty")

    cert_fd = os.memfd_create('smime-cert', os.MFD_CLOEXEC)
    try:
        os.write(cert_fd, cert_data)
        os.lseek(cert_fd, 0, os.SEEK_SET)
        # pass_fds inherits the fd into the child without FD_CLOEXEC,
        # preserving its numeric value so /dev/fd/{cert_fd} resolves.
        proc = subprocess.run(
            [openssl, 'smime', '-encrypt', cipher,
             '-outform', 'SMIME', f'/dev/fd/{cert_fd}'],
            input=plaintext,
            capture_output=True,
            check=False,
            pass_fds=(cert_fd,),
        )
        if proc.returncode != 0:
            raise SMIMEEncryptionError(
                f"openssl smime -encrypt failed (rc={proc.returncode}): "
                f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
            )
        return proc.stdout
    finally:
        os.close(cert_fd)


class SMIMEMailer:
    """S/MIME encrypted email sender backed by the openssl CLI."""

    def __init__(self, smtp_host, smtp_port=587, username=None, password=None, use_tls=True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    @staticmethod
    def _wrap_smime_with_headers(smime_blob: bytes, from_addr: str, to_addr: str, subject: str) -> bytes:
        # openssl emits a full SMIME message body but without the routing
        # headers. Prepend them so SMTP and recipient clients route correctly.
        headers = (
            f"From: {from_addr}\r\n"
            f"To: {to_addr}\r\n"
            f"Subject: {subject}\r\n"
        ).encode('utf-8')
        return headers + smime_blob

    def create_encrypted_email(self, from_addr, to_addr, subject, body, cert_data: bytes) -> bytes:
        inner = MIMEText(body, 'plain', 'utf-8').as_string()
        smime_blob = encrypt_smime(inner.encode('utf-8'), cert_data)
        return self._wrap_smime_with_headers(smime_blob, from_addr, to_addr, subject)

    def send_encrypted(self, from_addr, to_addr, subject, body, cert_data: bytes) -> None:
        payload = self.create_encrypted_email(from_addr, to_addr, subject, body, cert_data)
        self._send_smtp(from_addr, to_addr, payload)

    def _send_smtp(self, from_addr: str, to_addr: str, payload: bytes) -> None:
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(from_addr, to_addr, payload)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="S/MIME encrypted email via openssl CLI (in-memory cert)")
    parser.add_argument("--smtp-host", required=True)
    parser.add_argument("--smtp-port", type=int, default=587)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--from", dest="from_addr", required=True)
    parser.add_argument("--to", dest="to_addr", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument(
        "--cert",
        required=True,
        help="Cert file path. Read into memory at startup; never reopened or passed to openssl by path.",
    )
    args = parser.parse_args()

    # The CLI demo reads cert bytes here at the boundary. In a real
    # deployment, replace this with your AD/LDAP fetch.
    cert_bytes = Path(args.cert).read_bytes()

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
        cert_data=cert_bytes,
    )
    print(f"Encrypted email sent to {args.to_addr}")
