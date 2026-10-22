"""Erzeugt bei Bedarf ein selbstsigniertes Zertifikat für HTTPS im Heimnetz."""
import ipaddress
import os
import socket
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def ensure_cert(tls_dir) -> tuple[str, str]:
    cert_path, key_path = tls_dir / "zertifikat.pem", tls_dir / "schluessel.pem"
    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)
    tls_dir.mkdir(parents=True, exist_ok=True)

    names = {"localhost", socket.gethostname()}
    ips = {"127.0.0.1"}
    for extra in filter(None, (s.strip() for s in os.environ.get("LAGER_TLS_SAN", "").split(","))):
        try:
            ipaddress.ip_address(extra)
            ips.add(extra)
        except ValueError:
            names.add(extra)
    san = [x509.DNSName(n) for n in sorted(names)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Lager Heim"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Lager Heim (selbstsigniert)")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(cert_path), str(key_path)
