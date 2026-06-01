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
    - You inherit the system openssl's defaults and bugs.

Two encryption entry points:
    encrypt_smime(plaintext, cert_path)
        Cert read from a file on disk by openssl directly.

    encrypt_smime_in_memory(plaintext, cert_pem)
        Cert passed through bash process substitution as
        `<(printf '%s' "$SMIME_CERT")` and never touches the filesystem.
        Use when the cert comes from a runtime source like LDAP/AD.
        PEM only (env vars can't carry binary safely). Requires bash.

Requirements:
    The `openssl` binary on PATH. No Python deps beyond the stdlib.
    The in-memory variant additionally requires `bash` on PATH.
"""

# pattern: Imperative Shell

import os
import shlex
import shutil
import smtplib
import subprocess
from email.mime.text import MIMEText


class OpenSSLNotFoundError(RuntimeError):
    """Raised when the openssl binary is not available on PATH."""


class BashUnavailableError(RuntimeError):
    """Raised when bash is not available (required for in-memory variant)."""


class SMIMEEncryptionError(RuntimeError):
    """Raised when openssl exits non-zero during encryption."""


def _require_openssl() -> str:
    path = shutil.which('openssl')
    if path is None:
        raise OpenSSLNotFoundError("openssl binary not found on PATH")
    return path


def _require_bash() -> str:
    path = shutil.which('bash')
    if path is None:
        raise BashUnavailableError("bash binary not found on PATH")
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


def encrypt_smime_in_memory(plaintext: bytes, cert_pem, cipher: str = '-aes-256-cbc') -> bytes:
    """Encrypt via openssl, exposing the cert through bash process substitution.

    Runs the equivalent of:
        openssl smime -encrypt <cipher> -outform SMIME <(printf '%s' "$SMIME_CERT")

    The cert is passed to a bash subprocess in an env var, then written
    through process substitution into a /dev/fd/N path that openssl reads.
    The cert never touches the filesystem.

    PEM only: env vars are NUL-terminated C strings, so DER (binary) certs
    can't survive the trip. Convert DER to PEM upstream if needed.
    """
    openssl = _require_openssl()
    bash = _require_bash()
    if isinstance(cert_pem, bytes):
        cert_pem = cert_pem.decode('utf-8')
    if not cert_pem:
        raise SMIMEEncryptionError("cert is empty")
    if '\x00' in cert_pem:
        raise SMIMEEncryptionError("cert contains NUL byte; PEM expected, DER passed?")

    bash_script = (
        f'exec {shlex.quote(openssl)} smime -encrypt {cipher} -outform SMIME '
        f'<(printf "%s" "$SMIME_CERT")'
    )
    proc = subprocess.run(
        [bash, '-c', bash_script],
        input=plaintext,
        capture_output=True,
        check=False,
        env={**os.environ, 'SMIME_CERT': cert_pem},
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

    def create_encrypted_email(self, from_addr, to_addr, subject, body, recipient_cert_path) -> bytes:
        inner = MIMEText(body, 'plain', 'utf-8').as_string()
        smime_blob = encrypt_smime(inner.encode('utf-8'), recipient_cert_path)
        return self._wrap_smime_with_headers(smime_blob, from_addr, to_addr, subject)

    def create_encrypted_email_from_cert_bytes(
        self, from_addr, to_addr, subject, body, cert_pem,
    ) -> bytes:
        """Build an encrypted email when the cert is held in memory (e.g. from AD).

        Cert never persisted to disk; passed via bash process substitution.
        """
        inner = MIMEText(body, 'plain', 'utf-8').as_string()
        smime_blob = encrypt_smime_in_memory(inner.encode('utf-8'), cert_pem)
        return self._wrap_smime_with_headers(smime_blob, from_addr, to_addr, subject)

    def send_encrypted(self, from_addr, to_addr, subject, body, recipient_cert_path) -> None:
        payload = self.create_encrypted_email(from_addr, to_addr, subject, body, recipient_cert_path)
        self._send_smtp(from_addr, to_addr, payload)

    def send_encrypted_with_cert_bytes(
        self, from_addr, to_addr, subject, body, cert_pem,
    ) -> None:
        """Send an encrypted email using a cert held only in memory."""
        payload = self.create_encrypted_email_from_cert_bytes(
            from_addr, to_addr, subject, body, cert_pem,
        )
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
