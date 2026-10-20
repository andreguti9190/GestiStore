"""Genera una CA local y un certificado TLS para la IP de la demo."""

import argparse
import ipaddress
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


CA_CERT_FILENAME = 'amperestore-ca.cer'
CA_KEY_FILENAME = 'amperestore-ca-key.pem'
SERVER_CERT_FILENAME = 'amperestore-server-fullchain.pem'
SERVER_KEY_FILENAME = 'amperestore-server-key.pem'


def _write_private_key(path, key):
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _create_ca(output_dir):
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'AmpereStore local'),
        x509.NameAttribute(NameOID.COMMON_NAME, 'AmpereStore Local Development CA'),
    ])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_private_key(output_dir / CA_KEY_FILENAME, key)
    (output_dir / CA_CERT_FILENAME).write_bytes(
        certificate.public_bytes(serialization.Encoding.DER)
    )
    return key, certificate


def _load_or_create_ca(output_dir):
    cert_path = output_dir / CA_CERT_FILENAME
    key_path = output_dir / CA_KEY_FILENAME
    if cert_path.exists() and key_path.exists():
        try:
            certificate = x509.load_der_x509_certificate(cert_path.read_bytes())
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if certificate.public_key().public_numbers() == key.public_key().public_numbers():
                return key, certificate
        except (ValueError, TypeError):
            pass
    return _create_ca(output_dir)


def _validate_hostname(hostname):
    hostname = hostname.strip().rstrip('.').lower()
    if (
        not hostname
        or len(hostname) > 253
        or not re.fullmatch(r'[a-z0-9.-]+', hostname)
        or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
               for label in hostname.split('.'))
    ):
        raise ValueError('El dominio HTTPS no es válido.')
    return hostname


def generate_certificate(ip, output_dir, hostname=None):
    ip_address = ipaddress.ip_address(ip)
    if ip_address.version != 4:
        raise ValueError('Solo se admiten direcciones IPv4 para iniciar_red.ps1.')

    hostname = _validate_hostname(hostname or f'{str(ip_address).replace(".", "-")}.sslip.io')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ca_key, ca_certificate = _load_or_create_ca(output_dir)

    now = datetime.now(timezone.utc)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'AmpereStore local'),
        x509.NameAttribute(NameOID.COMMON_NAME, str(ip_address)),
    ])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.IPAddress(ip_address),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
                x509.DNSName('localhost'),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_private_key(output_dir / SERVER_KEY_FILENAME, server_key)
    (output_dir / SERVER_CERT_FILENAME).write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
        + ca_certificate.public_bytes(serialization.Encoding.PEM)
    )
    return {
        'ca_certificate': output_dir / CA_CERT_FILENAME,
        'server_certificate': output_dir / SERVER_CERT_FILENAME,
        'server_key': output_dir / SERVER_KEY_FILENAME,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    paths = generate_certificate(args.ip, args.output_dir, args.hostname)
    for name, path in paths.items():
        print(f'{name}={path.resolve()}')


if __name__ == '__main__':
    main()
