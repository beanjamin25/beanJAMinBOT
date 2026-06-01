"""
S/MIME Email Encryption using endesive (>=2.x) on cryptography>=36

Approach: let endesive handle all CMS structure building and S/MIME framing.
This is the smallest implementation by far, but adds a dependency you don't
fully control and is less battle-tested for email than for PDF signing.

endesive itself depends on asn1crypto + cryptography under the hood, so this
is effectively a higher-level facade over the EmailEncrypt3.py approach.

Requirements:
    pip install endesive cryptography>=36
"""

import smtplib

from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from endesive.email import encrypt as endesive_encrypt
from endesive.email import sign as endesive_sign


def _load_cert(path: str) -> x509.Certificate:
    data = open(path, 'rb').read()
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError:
        return x509.load_der_x509_certificate(data)


def _load_key(path: str, password: bytes | None):
    return load_pem_private_key(open(path, 'rb').read(), password=password)


def _prepend_routing_headers(mime_body: bytes, from_addr: str, to_addr: str, subject: str) -> bytes:
    # endesive returns a MIME part with Content-Type / Content-Disposition only.
    # Prepend the SMTP envelope headers so the message routes correctly.
    headers = (
        f"From: {from_addr}\r\n"
        f"To: {to_addr}\r\n"
        f"Subject: {subject}\r\n"
    ).encode('utf-8')
    return headers + mime_body


class SMIMEMailer:
    """S/MIME encrypted email sender backed by endesive."""

    def __init__(self, smtp_host, smtp_port=587, username=None, password=None, use_tls=True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def create_encrypted_email(self, from_addr, to_addr, subject, body, recipient_cert_path) -> bytes:
        cert = _load_cert(recipient_cert_path)
        cms_mime = endesive_encrypt(body.encode('utf-8'), [cert])
        # endesive's annotation says -> bytes but it actually returns str
        if isinstance(cms_mime, str):
            cms_mime = cms_mime.encode('utf-8')
        return _prepend_routing_headers(cms_mime, from_addr, to_addr, subject)

    def create_signed_and_encrypted_email(
        self,
        from_addr,
        to_addr,
        subject,
        body,
        sender_cert_path,
        sender_key_path,
        recipient_cert_path,
        key_password: bytes | None = None,
    ) -> bytes:
        sender_cert = _load_cert(sender_cert_path)
        sender_key = _load_key(sender_key_path, key_password)
        recipient_cert = _load_cert(recipient_cert_path)

        # sign() returns a complete multipart/signed MIME envelope
        signed = endesive_sign(body.encode('utf-8'), sender_key, sender_cert, [], 'sha256')
        if isinstance(signed, str):
            signed = signed.encode('utf-8')

        # encrypt() the whole signed envelope
        encrypted = endesive_encrypt(signed, [recipient_cert])
        if isinstance(encrypted, str):
            encrypted = encrypted.encode('utf-8')

        return _prepend_routing_headers(encrypted, from_addr, to_addr, subject)

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

    parser = argparse.ArgumentParser(description="S/MIME encrypted email via endesive")
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
