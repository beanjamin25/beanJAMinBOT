"""
S/MIME Email Encryption using asn1crypto + cryptography (>=36)

Approach: build CMS EnvelopedData declaratively with asn1crypto's typed
ASN.1 schema (full RFC 5652 coverage), and use cryptography only for the
AES/RSA primitives. Works on cryptography 36 since it never touches the
pkcs7 module that was added in 43.

Requirements:
    pip install asn1crypto cryptography>=36
"""

import base64
import os
import smtplib
from email.message import EmailMessage
from email.mime.text import MIMEText

from asn1crypto import algos, cms, core
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import Encoding


# =============================================================================
# Pure functional core: build CMS EnvelopedData
# =============================================================================

def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def build_enveloped_data_der(content: bytes, recipient_cert: x509.Certificate) -> bytes:
    """Return DER-encoded CMS ContentInfo wrapping EnvelopedData."""
    cek = os.urandom(32)  # AES-256
    iv = os.urandom(16)

    # Encrypt the payload with the symmetric CEK
    cipher = Cipher(algorithms.AES(cek), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_content = encryptor.update(_pkcs7_pad(content)) + encryptor.finalize()

    # Wrap CEK in RSA PKCS#1 v1.5 using the recipient's public key
    encrypted_cek = recipient_cert.public_key().encrypt(cek, padding.PKCS1v15())

    # Re-parse the cert through asn1crypto so we can reference its
    # issuer/serial structurally rather than poking at DER bytes
    asn1_cert = asn1_x509.Certificate.load(recipient_cert.public_bytes(Encoding.DER))

    recipient_info = cms.RecipientInfo(
        name='ktri',
        value=cms.KeyTransRecipientInfo({
            'version': 'v0',
            'rid': cms.RecipientIdentifier(
                name='issuer_and_serial_number',
                value=cms.IssuerAndSerialNumber({
                    'issuer': asn1_cert.issuer,
                    'serial_number': asn1_cert.serial_number,
                }),
            ),
            'key_encryption_algorithm': cms.KeyEncryptionAlgorithm({
                'algorithm': 'rsaes_pkcs1v15',
            }),
            'encrypted_key': encrypted_cek,
        }),
    )

    enc_content_info = cms.EncryptedContentInfo({
        'content_type': 'data',
        'content_encryption_algorithm': cms.EncryptionAlgorithm({
            'algorithm': 'aes256_cbc',
            'parameters': core.OctetString(iv),
        }),
        'encrypted_content': encrypted_content,
    })

    enveloped = cms.EnvelopedData({
        'version': 'v0',
        'recipient_infos': cms.RecipientInfos([recipient_info]),
        'encrypted_content_info': enc_content_info,
    })

    return cms.ContentInfo({
        'content_type': 'enveloped_data',
        'content': enveloped,
    }).dump()


# =============================================================================
# Imperative shell: load files, build MIME, talk to SMTP
# =============================================================================

class SMIMEMailer:
    """S/MIME encrypted email sender backed by asn1crypto + cryptography>=36."""

    def __init__(self, smtp_host, smtp_port=587, username=None, password=None, use_tls=True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def load_certificate(self, cert_path: str) -> x509.Certificate:
        with open(cert_path, 'rb') as f:
            data = f.read()
        try:
            return x509.load_pem_x509_certificate(data)
        except ValueError:
            return x509.load_der_x509_certificate(data)

    def encrypt_message(self, message: str, recipient_cert_path: str) -> bytes:
        cert = self.load_certificate(recipient_cert_path)
        return build_enveloped_data_der(message.encode('utf-8'), cert)

    def create_encrypted_email(self, from_addr, to_addr, subject, body, recipient_cert_path) -> str:
        inner = MIMEText(body, 'plain', 'utf-8').as_string()
        cms_der = self.encrypt_message(inner, recipient_cert_path)

        msg = EmailMessage()
        msg['From'] = from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg['MIME-Version'] = '1.0'
        msg['Content-Type'] = (
            'application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"'
        )
        msg['Content-Transfer-Encoding'] = 'base64'
        msg['Content-Disposition'] = 'attachment; filename="smime.p7m"'

        # RFC 2045: base64 lines wrapped at 76 chars
        b64 = base64.b64encode(cms_der).decode('ascii')
        msg.set_payload('\n'.join(b64[i:i+76] for i in range(0, len(b64), 76)))
        return msg.as_string()

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

    parser = argparse.ArgumentParser(description="S/MIME encrypted email via asn1crypto")
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
