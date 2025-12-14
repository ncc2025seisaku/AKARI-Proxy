import http.server
import ssl
import sys
import os
import tempfile
from socketserver import ThreadingMixIn
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert(cert_path, key_path):
    """Generates a self-signed certificate and key using cryptography library."""
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"JP"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Tokyo"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Minato"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"AKARI Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=1)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    ).sign(key, hashes.SHA256())

    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class RespondingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/100k":
            data = b"x" * 100_000
            self._send_data(data)
        elif self.path == "/1m":
            data = b"x" * 1_000_000
            self._send_data(data)
        elif self.path == "/10m":
            # 10MB data
            data = b"x" * 10_000_000
            self._send_data(data)
        elif self.path == "/":
             self.send_response(200)
             self.send_header("Content-Type", "text/plain")
             self.end_headers()
             self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _send_data(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # Silence logs to avoid cluttering output
        pass

def main():
    port = 8443
    cert_file = "temp_cert.pem"
    key_file = "temp_key.pem"
    
    # Always regenerate to ensure validity
    print("Generating self-signed cert...")
    try:
        generate_self_signed_cert(cert_file, key_file)
    except ImportError:
        print("Error: 'cryptography' library is required. Please install it: pip install cryptography")
        sys.exit(1)

    server_address = ('0.0.0.0', port)
    httpd = ThreadingHTTPServer(server_address, RespondingHandler)
    
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving HTTPS on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(cert_file): os.remove(cert_file)
        if os.path.exists(key_file): os.remove(key_file)

if __name__ == "__main__":
    main()
