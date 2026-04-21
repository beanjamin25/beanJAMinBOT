"""
S/MIME Email Encryption using PyCA/cryptography

Migrated from M2Crypto following the official migration guide:
https://m2crypto.readthedocs.io/en/latest/howto.migration.html

Encrypts and sends emails using X509 certificates, compatible with
enterprise email clients like Outlook.

Requirements:
    pip install cryptography>=43.0.0

Usage:
    from EmailEncrypt2 import SMIMEMailer

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

Migration notes (M2Crypto → cryptography):
    - X509.load_cert(path) → x509.load_pem_x509_certificate(data)
    - X509.X509_Stack() → list of certificates
    - BIO.MemoryBuffer(data) → bytes directly
    - SMIME.SMIME().encrypt() → pkcs7.PKCS7EnvelopeBuilder
    - SMIME.SMIME().sign() → pkcs7.PKCS7SignatureBuilder
    - SMIME.Cipher('aes_256_cbc') → algorithms.AES256
"""

import smtplib
from email.mime.text import MIMEText

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    load_pem_private_key,
    pkcs7,
)
from cryptography.hazmat.primitives.ciphers import algorithms


class SMIMEMailer:
    """Handles S/MIME encryption and email sending using PyCA/cryptography."""

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
        Load an X509 certificate from a PEM file.

        M2Crypto:
            cert = X509.load_cert(cert_path)

        cryptography:
            with open(cert_path, 'rb') as f:
                cert = x509.load_pem_x509_certificate(f.read())

        Args:
            cert_path: Path to the certificate file

        Returns:
            cryptography x509.Certificate object
        """
        with open(cert_path, 'rb') as cert_file:
            cert_data = cert_file.read()

        # Try PEM format first, fall back to DER
        try:
            return x509.load_pem_x509_certificate(cert_data)
        except ValueError:
            return x509.load_der_x509_certificate(cert_data)

    def load_private_key(self, key_path, password=None):
        """
        Load a private key from a PEM file.

        M2Crypto:
            smime.load_key(key_path, cert_path, callback=lambda _: password)

        cryptography:
            key = load_pem_private_key(data, password=password)

        Args:
            key_path: Path to the private key file
            password: Password for encrypted keys (bytes or None)

        Returns:
            Private key object
        """
        with open(key_path, 'rb') as key_file:
            key_data = key_file.read()

        if password and isinstance(password, str):
            password = password.encode()

        return load_pem_private_key(key_data, password=password)

    def encrypt_message(self, message, recipient_cert_path):
        """
        Encrypt a message using S/MIME with the recipient's X509 certificate.

        M2Crypto:
            smime = SMIME.SMIME()
            cert_stack = X509.X509_Stack()
            cert_stack.push(X509.load_cert(recipient_cert_path))
            smime.set_x509_stack(cert_stack)
            smime.set_cipher(SMIME.Cipher('aes_256_cbc'))
            msg_bio = BIO.MemoryBuffer(message.encode('utf-8'))
            encrypted = smime.encrypt(msg_bio)
            out_bio = BIO.MemoryBuffer()
            smime.write(out_bio, encrypted)
            return out_bio.read()

        cryptography:
            Uses PKCS7EnvelopeBuilder (available in cryptography >= 43.0.0)

        Args:
            message: The email message string to encrypt
            recipient_cert_path: Path to recipient's X509 certificate (PEM format)

        Returns:
            Encrypted message as bytes (S/MIME format)
        """
        # Load recipient certificate (was: X509.load_cert + X509_Stack)
        cert = self.load_certificate(recipient_cert_path)

        # Build and encrypt the message
        # M2Crypto used: smime.set_cipher(SMIME.Cipher('aes_256_cbc'))
        # cryptography uses: algorithms.AES256
        encrypted = (
            pkcs7.PKCS7EnvelopeBuilder()
            .set_data(message.encode('utf-8'))
            .add_recipient(cert)
            .encrypt(Encoding.SMIME, algorithms.AES256)
        )

        return encrypted

    def create_mime_message(self, from_addr, to_addr, subject, body):
        """
        Create a MIME message structure.

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            subject: Email subject
            body: Email body text

        Returns:
            Formatted MIME message string
        """
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
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
        # Create the plain MIME message
        plain_message = self.create_mime_message(from_addr, to_addr, subject, body)

        # Encrypt the message
        encrypted_message = self.encrypt_message(plain_message, recipient_cert_path)

        # Send via SMTP
        self._send_smtp(from_addr, to_addr, encrypted_message)

    def send_signed_and_encrypted(self, from_addr, to_addr, subject, body,
                                   sender_cert_path, sender_key_path,
                                   recipient_cert_path, key_password=None):
        """
        Sign, encrypt, and send an email.

        M2Crypto:
            smime = SMIME.SMIME()
            smime.load_key(sender_key_path, sender_cert_path)
            signed = smime.sign(msg_bio, SMIME.PKCS7_DETACHED)
            # then encrypt...

        cryptography:
            Uses PKCS7SignatureBuilder then PKCS7EnvelopeBuilder

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            subject: Email subject
            body: Email body text
            sender_cert_path: Path to sender's X509 certificate
            sender_key_path: Path to sender's private key
            recipient_cert_path: Path to recipient's X509 certificate
            key_password: Password for sender's private key (if encrypted)
        """
        # Load sender's certificate and key for signing
        # M2Crypto: smime.load_key(key_path, cert_path, callback=...)
        sender_cert = self.load_certificate(sender_cert_path)
        sender_key = self.load_private_key(sender_key_path, key_password)

        # Create the plain message
        plain_message = self.create_mime_message(from_addr, to_addr, subject, body)

        # Sign the message
        # M2Crypto: signed = smime.sign(msg_bio, SMIME.PKCS7_DETACHED)
        signed = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(plain_message.encode('utf-8'))
            .add_signer(sender_cert, sender_key, hashes.SHA256(), rsa_padding=padding.PKCS1v15())
            .sign(Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
        )

        # Combine original message with signature for encryption
        # Create multipart/signed message
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        import base64

        outer = MIMEMultipart('signed', protocol='application/pkcs7-signature', micalg='sha-256')
        outer['From'] = from_addr
        outer['To'] = to_addr
        outer['Subject'] = subject

        # Add the original content
        text_part = MIMEText(body, 'plain', 'utf-8')
        outer.attach(text_part)

        # Add the signature
        sig_part = MIMEBase('application', 'pkcs7-signature', name='smime.p7s')
        sig_part.set_payload(base64.b64encode(signed).decode('ascii'))
        sig_part['Content-Transfer-Encoding'] = 'base64'
        sig_part['Content-Disposition'] = 'attachment; filename="smime.p7s"'
        outer.attach(sig_part)

        signed_message = outer.as_string()

        # Encrypt the signed message
        # M2Crypto: encrypt_smime.encrypt(signed_bio)
        recipient_cert = self.load_certificate(recipient_cert_path)
        encrypted = (
            pkcs7.PKCS7EnvelopeBuilder()
            .set_data(signed_message.encode('utf-8'))
            .add_recipient(recipient_cert)
            .encrypt(Encoding.SMIME, algorithms.AES256)
        )

        # Send via SMTP
        self._send_smtp(from_addr, to_addr, encrypted)

    def _send_smtp(self, from_addr, to_addr, message):
        """
        Send a message via SMTP.

        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            message: The message bytes to send
        """
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(from_addr, to_addr, message)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Send S/MIME encrypted email (PyCA/cryptography)")
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
