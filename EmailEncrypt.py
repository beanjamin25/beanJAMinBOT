"""
S/MIME Email Encryption using M2Crypto

Encrypts and sends emails using X509 certificates, compatible with
enterprise email clients like Outlook.

Requirements:
    pip install M2Crypto

Usage:
    from EmailEncrypt import SMIMEMailer

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

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from M2Crypto import BIO, SMIME, X509


class SMIMEMailer:
    """Handles S/MIME encryption and email sending."""

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

        Args:
            cert_path: Path to the certificate file

        Returns:
            X509.X509 certificate object
        """
        return X509.load_cert(cert_path)

    def encrypt_message(self, message, recipient_cert_path):
        """
        Encrypt a message using S/MIME with the recipient's X509 certificate.

        Args:
            message: The email message string to encrypt
            recipient_cert_path: Path to recipient's X509 certificate (PEM format)

        Returns:
            Encrypted message as bytes
        """
        smime = SMIME.SMIME()

        # Load recipient certificate into a certificate stack
        cert_stack = X509.X509_Stack()
        cert = self.load_certificate(recipient_cert_path)
        cert_stack.push(cert)
        smime.set_x509_stack(cert_stack)

        # Set cipher (AES-256-CBC is widely supported by Outlook)
        smime.set_cipher(SMIME.Cipher('aes_256_cbc'))

        # Create a buffer with the message
        msg_bio = BIO.MemoryBuffer(message.encode('utf-8'))

        # Encrypt the message
        encrypted = smime.encrypt(msg_bio)

        # Write encrypted message to buffer
        out_bio = BIO.MemoryBuffer()
        smime.write(out_bio, encrypted)

        return out_bio.read()

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
        smime = SMIME.SMIME()

        # Load sender's certificate and key for signing
        if key_password:
            smime.load_key(sender_key_path, sender_cert_path,
                          callback=lambda _: key_password.encode())
        else:
            smime.load_key(sender_key_path, sender_cert_path)

        # Create the plain message
        plain_message = self.create_mime_message(from_addr, to_addr, subject, body)
        msg_bio = BIO.MemoryBuffer(plain_message.encode('utf-8'))

        # Sign the message
        signed = smime.sign(msg_bio, SMIME.PKCS7_DETACHED)

        # Prepare signed message for encryption
        signed_bio = BIO.MemoryBuffer()
        smime.write(signed_bio, signed, msg_bio)

        # Now encrypt with recipient's certificate
        encrypt_smime = SMIME.SMIME()
        cert_stack = X509.X509_Stack()
        cert = self.load_certificate(recipient_cert_path)
        cert_stack.push(cert)
        encrypt_smime.set_x509_stack(cert_stack)
        encrypt_smime.set_cipher(SMIME.Cipher('aes_256_cbc'))

        # Encrypt the signed message
        encrypted = encrypt_smime.encrypt(signed_bio)

        # Write final message
        out_bio = BIO.MemoryBuffer()
        encrypt_smime.write(out_bio, encrypted)

        # Send via SMTP
        self._send_smtp(from_addr, to_addr, out_bio.read())

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
    # Example usage
    import argparse

    parser = argparse.ArgumentParser(description="Send S/MIME encrypted email")
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
