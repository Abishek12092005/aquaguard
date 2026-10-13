"""A minimal SMTP sink for testing: accepts mail, saves every message to a file.

Implements just enough of the protocol for `smtplib` with STARTTLS refused and
AUTH LOGIN/PLAIN accepted unconditionally. Every received message is APPENDED to
`messages.log` so the test can verify the attachment actually arrived.
"""

import socket
import socketserver
import base64
import threading

HOST, PORT = "127.0.0.1", 1025
OUT = r"C:\Users\abishek\OneDrive\Desktop\aquagaurd\smtp_messages.log"
lock = threading.Lock()


class Handler(socketserver.StreamRequestHandler):
    def send(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")

    def handle(self) -> None:
        self.send(b"220 aquaguard-test ESMTP sink")
        data_mode = False
        message = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            raw_line = line.rstrip(b"\r\n")
            cmd = raw_line.strip()
            if data_mode:
                if cmd == b".":
                    data_mode = False
                    with lock, open(OUT, "ab") as fh:
                        fh.write(b"\r\n=====MESSAGE=====\r\n")
                        # CRLF, NOT "\n". The lines arrive from the wire with
                        # their own \r\n intact (raw_line only rstripped the
                        # trailing pair), and they have to be written back out
                        # with that SAME terminator.
                        #
                        # Joining with "\n" instead produced a log where every
                        # message was one flat block with no line breaks, so
                        # `email.message_from_string` read the whole thing as a
                        # single text/plain body: the `Subject:` line ended up
                        # INSIDE the body, there was no header block, and any
                        # test walking `msg.walk()` for a named attachment found
                        # nothing at all. Joining with CRLF restores the
                        # structure, and a message that round-trips through the
                        # stdlib parser is the only proof the sink stored what
                        # was actually transmitted.
                        #
                        # The FRAMING lines use CRLF too, and that matters for the
                        # same reason: the separator is glued directly onto the
                        # first header line, so a bare "\n" there left a stray
                        # line break in front of `From:` and the parser saw the
                        # first header as malformed.
                        fh.write(b"\r\n".join(message))
                        fh.write(b"\r\n=====END=====\r\n")
                    message = []
                    self.send(b"250 OK stored")
                else:
                    # Un-dot-stuff the payload, KEEPING the original leading
                    # whitespace so MIME header folding survives intact.
                    message.append(raw_line[1:] if raw_line.startswith(b"..") else raw_line)
                continue
            verb = cmd.split(b" ", 1)[0].upper()
            if verb == b"EHLO" or verb == b"HELO":
                self.wfile.write(b"250-aquaguard-test\r\n250-AUTH LOGIN PLAIN\r\n250 OK\r\n")
            elif verb == b"AUTH":
                # Reply 334 (username prompt), then accept whatever comes back.
                self.send(b"334 VXNlcm5hbWU6")
                cred = self.rfile.readline()
                if cred.strip().upper() not in (b"*",):
                    self.send(b"334 UGFzc3dvcmQ6")
                    self.rfile.readline()
                self.send(b"235 OK authenticated")
            elif verb == b"MAIL" or verb == b"RCPT":
                self.send(b"250 OK")
            elif verb == b"DATA":
                data_mode = True
                self.send(b"354 End with <CRLF>.<CRLF>")
            elif verb == b"RSET" or verb == b"NOOP":
                self.send(b"250 OK")
            elif verb == b"QUIT":
                self.send(b"221 Bye")
                return
            else:
                self.send(b"250 OK")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"SMTP sink on {HOST}:{PORT}, writing to {OUT}", flush=True)
    Server((HOST, PORT), Handler).serve_forever()
