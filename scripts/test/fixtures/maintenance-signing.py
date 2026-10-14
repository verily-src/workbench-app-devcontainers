#!/usr/bin/env python3
"""Check curl's EC2 signature with fake IMDS credentials and an independent verifier."""

import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.parse

ACCESS = "EXAMPLEACCESSKEY"
SECRET = "FAKESecret"
SESSION = "FAKESession"
TOKEN = "FAKEMetadataToken"
errors = []
requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_PUT(self):
        assert self.path == "/latest/api/token"
        assert self.headers["X-aws-ec2-metadata-token-ttl-seconds"] == "60"
        self.reply(TOKEN)

    def do_GET(self):
        assert self.headers["X-aws-ec2-metadata-token"] == TOKEN
        if self.path == "/latest/dynamic/instance-identity/document":
            self.reply(json.dumps({"region": "us-east-1", "instanceId": "i-0123456789abcdef0"}))
        elif self.path == "/latest/meta-data/iam/security-credentials/":
            self.reply("TestRole")
        elif self.path == "/latest/meta-data/iam/security-credentials/TestRole":
            self.reply(json.dumps({"Code": "Success", "AccessKeyId": ACCESS,
                                   "SecretAccessKey": SECRET, "Token": SESSION}))
        else:
            raise AssertionError(self.path)

    def do_POST(self):
        try:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            params = urllib.parse.parse_qs(body.decode(), strict_parsing=True)
            assert params["Action"] == ["CreateTags"]
            assert params["Version"] == ["2016-11-15"]
            assert params["ResourceId.1"] == ["i-0123456789abcdef0"]
            assert params["Tag.1.Key"] == ["vwbapp:startup_script/message"]
            assert params["Tag.2.Key"] == ["vwbapp:startup_script/status"]
            assert params["Tag.2.Value"] == ["ERROR"]
            assert len(params["Tag.1.Value"][0].encode("ascii")) <= 256
            assert self.headers["X-Amz-Security-Token"] == SESSION
            assert self.headers["Host"] == "ec2.us-east-1.amazonaws.com"
            algorithm, value = self.headers["Authorization"].split(" ", 1)
            assert algorithm == "AWS4-HMAC-SHA256"
            auth = dict(item.strip().split("=", 1) for item in value.split(","))
            access, scope = auth["Credential"].split("/", 1)
            assert access == ACCESS
            date, region, service, terminator = scope.split("/")
            assert (region, service, terminator) == ("us-east-1", "ec2", "aws4_request")
            names = auth["SignedHeaders"].split(";")
            assert "x-amz-security-token" in names
            headers = "".join(name + ":" + " ".join(self.headers[name].split()) + "\n" for name in names)
            canonical = "\n".join(("POST", "/", "", headers, auth["SignedHeaders"],
                                   hashlib.sha256(body).hexdigest()))
            to_sign = "\n".join((algorithm, self.headers["X-Amz-Date"], scope,
                                 hashlib.sha256(canonical.encode()).hexdigest()))
            key = ("AWS4" + SECRET).encode()
            for part in (date, region, service, terminator):
                key = hmac.new(key, part.encode(), hashlib.sha256).digest()
            signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
            assert hmac.compare_digest(signature, auth["Signature"])
            requests.append(params)
            self.reply("<CreateTagsResponse><return>true</return></CreateTagsResponse>")
        except Exception as error:
            errors.append(type(error).__name__ + ": " + str(error))
            self.send_error(400)


reporter, root = sys.argv[1:]
root = Path(root)
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
real_curl = shutil.which("curl")
assert real_curl
wrapper_dir = root / "real-curl-wrapper"
wrapper_dir.mkdir()
wrapper = wrapper_dir / "curl"
wrapper.write_text("""#!/usr/bin/env python3
import os, sys, urllib.parse
args = sys.argv[1:]
assert not any(value in ' '.join(args) for value in ('FAKESecret', 'FAKESession', 'FAKEMetadataToken'))
url = urllib.parse.urlsplit(args[-1])
assert url.hostname in ('169.254.169.254', 'ec2.us-east-1.amazonaws.com')
if '--proto' in args:
    args[args.index('--proto') + 1] = '=http'
args[-1] = 'http://127.0.0.1:' + os.environ['SIGNING_PORT'] + url.path
args += ['--header', 'Host: ' + url.hostname, '--noproxy', '*']
os.execv(os.environ['REAL_CURL'], [os.environ['REAL_CURL']] + args)
""")
wrapper.chmod(0o755)
env = os.environ | {"PATH": str(wrapper_dir) + os.pathsep + os.environ["PATH"],
                    "REAL_CURL": real_curl, "SIGNING_PORT": str(server.server_port),
                    "WORKBENCH_CLOUD": "aws", "SERVICE_RESULT": "exit-code"}
try:
    result = subprocess.run(["bash", "-x", reporter, str(root / "state")], env=env,
                            capture_output=True, text=True, timeout=15)
finally:
    server.shutdown()
    server.server_close()
assert result.returncode == 0, result.stdout + result.stderr + repr(errors)
assert len(requests) == 1, errors
assert not any(value in result.stdout + result.stderr for value in (SECRET, SESSION, TOKEN))
print("EC2 SigV4 request verified with fake IMDS credentials")
