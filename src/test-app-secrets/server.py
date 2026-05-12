import http.server
import os
import yaml


DELIVERY_TYPES = ["valueVar", "pathVar", "pipeVar"]


def load_secrets_yml():
    with open("/workspace/secrets.yml") as f:
        data = yaml.safe_load(f)
    entries = []
    for secret in data["secrets"]:
        for dtype in DELIVERY_TYPES:
            if dtype in secret:
                entries.append((secret[dtype], dtype))
    return entries


def read_secret(env_var):
    val = os.environ.get(env_var)
    if val is None:
        return ""
    if val.startswith("/dev/fd/"):
        try:
            with open(val) as f:
                return f.read()
        except OSError:
            return ""
    return val


SECRETS = load_secrets_yml()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        rows = ""
        for env_var, delivery_type in SECRETS:
            value = read_secret(env_var)
            rows += f"<tr><td>{env_var}</td><td>{delivery_type}</td><td>{value}</td></tr>\n"

        html = f"""<!DOCTYPE html>
<html>
<head><title>Secrets Test</title>
<style>
  body {{ font-family: monospace; margin: 2em; }}
  table {{ border-collapse: collapse; }}
  td, th {{ border: 1px solid #333; padding: 8px 12px; text-align: left; }}
</style>
</head>
<body>
<h2>Secrets</h2>
<table>
<tr><th>Name</th><th>Type</th><th>Value</th></tr>
{rows}</table>
<p>Reload to observe pipe secret behavior.</p>
</body>
</html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())


http.server.HTTPServer(("", 8080), Handler).serve_forever()
