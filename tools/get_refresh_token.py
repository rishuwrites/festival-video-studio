"""Obtain a Google OAuth refresh token with YouTube and Drive file scopes."""

import http.server
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/drive.file",
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _client_credentials():
    client_id = os.getenv("YT_CLIENT_ID", "").strip()
    client_secret = os.getenv("YT_CLIENT_SECRET", "").strip()
    client_file = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    if client_file:
        payload = json.loads(open(client_file, encoding="utf-8").read())
        settings = payload.get("installed") or payload.get("web") or {}
        client_id = client_id or settings.get("client_id", "")
        client_secret = client_secret or settings.get("client_secret", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Set YT_CLIENT_ID and YT_CLIENT_SECRET, or GOOGLE_OAUTH_CLIENT_FILE "
            "to a downloaded OAuth client JSON."
        )
    return client_id, client_secret


def _exchange_code(code, client_id, client_secret, redirect_uri):
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Google OAuth token exchange failed: {type(exc).__name__}") from exc
    refresh_token = payload.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Revoke the old app grant and rerun with consent."
        )
    return refresh_token


def get_refresh_token(open_browser=webbrowser.open):
    client_id, client_secret = _client_credentials()
    state = secrets.token_urlsafe(24)
    result = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result["error"] = "OAuth state validation failed"
                status = 400
                message = "OAuth state validation failed. You can close this tab."
            elif query.get("error"):
                result["error"] = query["error"][0]
                status = 400
                message = "Google OAuth was not completed. You can close this tab."
            else:
                result["code"] = query.get("code", [""])[0]
                status = 200
                message = "Authorization received. You can close this tab."
            body = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 180
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    auth_query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    authorization_url = f"{AUTH_URL}?{auth_query}"
    print("Opening the Google consent page. If it does not open, visit this URL:")
    print(authorization_url)
    open_browser(authorization_url)
    try:
        server.handle_request()
    finally:
        server.server_close()
    if result.get("error"):
        raise RuntimeError(f"Google OAuth authorization failed: {result['error']}")
    if not result.get("code"):
        raise RuntimeError("Timed out waiting for Google OAuth authorization")
    return _exchange_code(result["code"], client_id, client_secret, redirect_uri)


def main():
    token = get_refresh_token()
    print("\nNew YT_REFRESH_TOKEN (copy it directly into the repository secret):")
    print(token)
    print(
        "\nEnable YouTube Data API v3 and Google Drive API in this same Cloud project. "
        "Replace the YT_REFRESH_TOKEN secret with this value. If the OAuth consent screen "
        "is in Testing status, refresh tokens can expire after 7 days; set the app to "
        "In production or regenerate the token weekly."
    )


if __name__ == "__main__":
    main()
