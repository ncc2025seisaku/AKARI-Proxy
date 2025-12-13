import http.server
import ssl
import sys
import os
import tempfile
from socketserver import ThreadingMixIn

import datetime

# Cryptography removed for simple HTTP testing
def generate_self_signed_cert(cert_path, key_path):
    pass

class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class RespondingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/100k":
            data = b"x" * 100_000
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/1m":
            data = b"x" * 1_000_000
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        # Silence logs to avoid cluttering output
        pass

def main():
    port = 8443
    cert_file = "temp_cert.pem"
    key_file = "temp_key.pem"
    
    if not os.path.exists(cert_file) or not os.path.exists(key_file):
        print("Generating self-signed cert...")
        generate_self_signed_cert(cert_file, key_file)

    server_address = ('localhost', port)
    httpd = ThreadingHTTPServer(server_address, RespondingHandler)
    
    # context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    # httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving HTTP on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(cert_file): os.remove(cert_file)
        if os.path.exists(key_file): os.remove(key_file)

if __name__ == "__main__":
    main()
