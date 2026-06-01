"""
S/MIME Email Encryption using cryptography library

Encrypts and sends emails using X509 certificates, compatible with
enterprise email clients like Outlook.

Requirements:
    pip install cryptography

Usage:
    from EmailEncryptCrypto import SMIMEMailer

    mailer = SMIMEMailer(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="password"
    )
    mailer.send_encrypted(
        from_addr="sender@example.com",
        to_addr="recipient@example.com",
        subject="Secure Message",
        body="This is encrypted content.",
        recipient_cert_path="/path/to/recipient_cert.pem"
    )
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.message import EmailMessage
import base64

from cryptography import x509
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend


# =============================================================================
# Minimal DER/ASN.1 Encoder (no external dependencies)
# =============================================================================

class DER:
    """Minimal DER encoder for building CMS structures."""

    # ASN.1 tag constants
    INTEGER = 0x02
    OCTET_STRING = 0x04
    NULL = 0x05
    OID = 0x06
    SEQUENCE = 0x30
    SET = 0x31
    CONTEXT_0 = 0xA0  # [0] IMPLICIT
    CONTEXT_0_CONSTRUCTED = 0xA0

    @staticmethod
    def _encode_length(length):
        """Encode ASN.1 length in DER format."""
        if length < 128:
            return bytes([length])
        elif length < 256:
            return bytes([0x81, length])
        elif length < 65536:
            return bytes([0x82, (length >> 8) & 0xFF, length & 0xFF])
        else:
            return bytes([0x83, (length >> 16) & 0xFF, (length >> 8) & 0xFF, length & 0xFF])

    @staticmethod
    def _tag_length_value(tag, value):
        """Wrap value with tag and length."""
        return bytes([tag]) + DER._encode_length(len(value)) + value

    @staticmethod
    def integer(value):
        """Encode an integer."""
        if value == 0:
            return DER._tag_length_value(DER.INTEGER, b'\x00')

        # Convert to bytes (big-endian, signed)
        byte_len = (value.bit_length() + 8) // 8
        value_bytes = value.to_bytes(byte_len, byteorder='big', signed=False)

        # Ensure positive integers don't get interpreted as negative
        if value_bytes[0] & 0x80:
            value_bytes = b'\x00' + value_bytes

        return DER._tag_length_value(DER.INTEGER, value_bytes)

    @staticmethod
    def octet_string(data):
        """Encode an octet string."""
        return DER._tag_length_value(DER.OCTET_STRING, data)

    @staticmethod
    def null():
        """Encode NULL."""
        return bytes([DER.NULL, 0x00])

    @staticmethod
    def oid(oid_string):
        """Encode an OID from dotted string format."""
        parts = [int(p) for p in oid_string.split('.')]

        # First two components are encoded specially
        result = bytes([parts[0] * 40 + parts[1]])

        # Remaining components use base-128 encoding
        for part in parts[2:]:
            if part == 0:
                result += b'\x00'
            else:
                encoded = []
                while part:
                    encoded.append(part & 0x7F)
                    part >>= 7
                encoded.reverse()
                for i in range(len(encoded) - 1):
                    encoded[i] |= 0x80
                result += bytes(encoded)

        return DER._tag_length_value(DER.OID, result)

    @staticmethod
    def sequence(*items):
        """Encode a SEQUENCE."""
        return DER._tag_length_value(DER.SEQUENCE, b''.join(items))

    @staticmethod
    def set_of(*items):
        """Encode a SET."""
        return DER._tag_length_value(DER.SET, b''.join(items))

    @staticmethod
    def context_specific(tag_num, value, constructed=True):
        """Encode context-specific tagged value."""
        tag = 0xA0 | tag_num if constructed else 0x80 | tag_num
        return DER._tag_length_value(tag, value)


# =============================================================================
# OIDs used in S/MIME
# =============================================================================

class OID:
    """Common OIDs for S/MIME."""
    DATA = "1.2.840.113549.1.7.1"
    ENVELOPED_DATA = "1.2.840.113549.1.7.3"
    RSA_ENCRYPTION = "1.2.840.113549.1.1.1"
    AES_256_CBC = "2.16.840.1.101.3.4.1.42"


# =============================================================================
# CMS Structure Builder
# =============================================================================

class CMSBuilder:
    """Builds CMS EnvelopedData structures for S/MIME."""

    @staticmethod
    def build_algorithm_identifier(oid, parameters=None):
        """Build AlgorithmIdentifier structure."""
        if parameters is None:
            return DER.sequence(DER.oid(oid), DER.null())
        else:
            return DER.sequence(DER.oid(oid), parameters)

    @staticmethod
    def build_issuer_and_serial(cert):
        """Build IssuerAndSerialNumber from certificate."""
        # Get the raw DER-encoded issuer from the certificate
        issuer_der = cert.issuer.public_bytes()
        serial = cert.serial_number

        return DER.sequence(issuer_der, DER.integer(serial))

    @staticmethod
    def build_recipient_info(cert, encrypted_key):
        """Build KeyTransRecipientInfo structure."""
        # RecipientIdentifier (using issuerAndSerialNumber)
        issuer_and_serial = CMSBuilder.build_issuer_and_serial(cert)

        # KeyEncryptionAlgorithmIdentifier
        key_enc_alg = CMSBuilder.build_algorithm_identifier(OID.RSA_ENCRYPTION)

        # KeyTransRecipientInfo
        return DER.sequence(
            DER.integer(0),  # version
            issuer_and_serial,
            key_enc_alg,
            DER.octet_string(encrypted_key)
        )

    @staticmethod
    def build_encrypted_content_info(encrypted_content, iv):
        """Build EncryptedContentInfo structure."""
        # ContentEncryptionAlgorithmIdentifier with IV as parameter
        content_enc_alg = CMSBuilder.build_algorithm_identifier(
            OID.AES_256_CBC,
            DER.octet_string(iv)
        )

        # EncryptedContent as [0] IMPLICIT OCTET STRING
        encrypted_content_tagged = DER.context_specific(0, encrypted_content, constructed=False)

        return DER.sequence(
            DER.oid(OID.DATA),
            content_enc_alg,
            encrypted_content_tagged
        )

    @staticmethod
    def build_enveloped_data(content, recipient_cert):
        """
        Build complete CMS EnvelopedData structure.

        Args:
            content: Plaintext bytes to encrypt
            recipient_cert: Recipient's X509 certificate

        Returns:
            DER-encoded ContentInfo containing EnvelopedData
        """
        # Generate random content encryption key (CEK) and IV
        cek = os.urandom(32)  # 256-bit for AES-256
        iv = os.urandom(16)   # 128-bit for AES-CBC

        # PKCS7 pad the content
        block_size = 16
        padding_len = block_size - (len(content) % block_size)
        padded_content = content + bytes([padding_len] * padding_len)

        # Encrypt content with AES-256-CBC
        cipher = Cipher(algorithms.AES(cek), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted_content = encryptor.update(padded_content) + encryptor.finalize()

        # Encrypt CEK with recipient's public key (RSA PKCS#1 v1.5)
        public_key = recipient_cert.public_key()
        encrypted_cek = public_key.encrypt(cek, padding.PKCS1v15())

        # Build RecipientInfo
        recipient_info = CMSBuilder.build_recipient_info(recipient_cert, encrypted_cek)

        # Build EncryptedContentInfo
        encrypted_content_info = CMSBuilder.build_encrypted_content_info(encrypted_content, iv)

        # Build EnvelopedData
        enveloped_data = DER.sequence(
            DER.integer(0),  # version
            DER.set_of(recipient_info),  # recipientInfos
            encrypted_content_info
        )

        # Wrap in ContentInfo
        content_info = DER.sequence(
            DER.oid(OID.ENVELOPED_DATA),
            DER.context_specific(0, enveloped_data)
        )

        return content_info


# =============================================================================
# S/MIME Mailer
# =============================================================================

class SMIMEMailer:
    """Handles S/MIME encryption and email sending using cryptography library."""

    def __init__(self, smtp_host, smtp_port=587, username=None, password=None, use_tls=True):
        """
        Initialize the mailer with SMTP settings.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port (default 587 for TLS)
            username: SMTP authentication username
            password: SMTP authentication password
            use_tls: Whether to use STARTTLS (default True)
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def load_certificate(self, cert_path):
        """
        Load an X509 certificate from a PEM or DER file.

        Args:
            cert_path: Path to the certificate file

        Returns:
            cryptography x509.Certificate object
        """
        with open(cert_path, "rb") as f:
            cert_data = f.read()

        try:
            return x509.load_pem_x509_certificate(cert_data, default_backend())
        except ValueError:
            return x509.load_der_x509_certificate(cert_data, default_backend())

    def encrypt_message(self, message, recipient_cert_path):
        """
        Encrypt a message using S/MIME with the recipient's X509 certificate.

        Args:
            message: The email message string to encrypt
            recipient_cert_path: Path to recipient's X509 certificate

        Returns:
            DER-encoded CMS EnvelopedData
        """
        cert = self.load_certificate(recipient_cert_path)
        return CMSBuilder.build_enveloped_data(message.encode('utf-8'), cert)

    def create_encrypted_email(self, from_addr, to_addr, subject, body, recipient_cert_path):
        """
        Create an S/MIME encrypted email message.

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            subject: Email subject
            body: Email body text
            recipient_cert_path: Path to recipient's X509 certificate

        Returns:
            Complete email message string ready to send
        """
        # Create the inner MIME message
        inner_msg = MIMEText(body, 'plain', 'utf-8')

        # Encrypt the inner message
        encrypted_data = self.encrypt_message(inner_msg.as_string(), recipient_cert_path)

        # Create the outer S/MIME message
        msg = EmailMessage()
        msg['From'] = from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg['MIME-Version'] = '1.0'
        msg['Content-Type'] = 'application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"'
        msg['Content-Transfer-Encoding'] = 'base64'
        msg['Content-Disposition'] = 'attachment; filename="smime.p7m"'

        # Base64 encode with 76-char line wrapping (per RFC 2045)
        encoded_data = base64.b64encode(encrypted_data).decode('ascii')
        formatted_data = '\n'.join(
            encoded_data[i:i+76] for i in range(0, len(encoded_data), 76)
        )

        msg.set_payload(formatted_data)

        return msg.as_string()

    def send_encrypted(self, from_addr, to_addr, subject, body, recipient_cert_path):
        """
        Encrypt and send an email.

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            subject: Email subject
            body: Email body text
            recipient_cert_path: Path to recipient's X509 certificate
        """
        encrypted_email = self.create_encrypted_email(
            from_addr, to_addr, subject, body, recipient_cert_path
        )
        self._send_smtp(from_addr, to_addr, encrypted_email)

    def _send_smtp(self, from_addr, to_addr, message):
        """
        Send a message via SMTP.

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            message: The message string to send
        """
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(from_addr, to_addr, message)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send S/MIME encrypted email (cryptography library)")
    parser.add_argument("--smtp-host", required=True, help="SMTP server hostname")
    parser.add_argument("--smtp-port", type=int, default=587, help="SMTP port")
    parser.add_argument("--username", help="SMTP username")
    parser.add_argument("--password", help="SMTP password")
    parser.add_argument("--from", dest="from_addr", required=True, help="Sender address")
    parser.add_argument("--to", dest="to_addr", required=True, help="Recipient address")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body")
    parser.add_argument("--cert", required=True, help="Recipient certificate path")

    args = parser.parse_args()

    mailer = SMIMEMailer(
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        username=args.username,
        password=args.password
    )

    mailer.send_encrypted(
        from_addr=args.from_addr,
        to_addr=args.to_addr,
        subject=args.subject,
        body=args.body,
        recipient_cert_path=args.cert
    )

    print(f"Encrypted email sent to {args.to_addr}")
