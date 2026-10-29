"""Upload to Instagram via instagrapi (username/password) or the official Graph API."""
import time

import requests

import config


class InstagrapiPoster:
    def __init__(self, ask_code=None):
        """ask_code(prompt) -> str is called when Instagram asks for a security / 2FA code."""
        from instagrapi import Client

        if not (config.IG_USERNAME and config.IG_PASSWORD):
            raise RuntimeError("IG_USERNAME / IG_PASSWORD are required for IG_BACKEND=instagrapi")
        self.cl = Client()
        self.cl.delay_range = [2, 6]
        if ask_code:
            self.cl.challenge_code_handler = lambda username, choice: ask_code(
                f"Instagram sent a security code to your {getattr(choice, 'name', choice)}.\nEnter the code:")
        if config.IG_SESSION_FILE.exists():
            self.cl.load_settings(config.IG_SESSION_FILE)
        try:
            self.cl.login(config.IG_USERNAME, config.IG_PASSWORD)
        except Exception as e:
            if type(e).__name__ == "ClientNeedsUpgradeError":
                raise RuntimeError("Instagram is currently blocking ID/password logins from this tool "
                                   "('app out of date'). Switch to the official API login.") from e
            if not ask_code or "TwoFactorRequired" not in type(e).__name__:
                raise
            code = ask_code("Enter the 6-digit code from your two-factor authentication app / SMS:")
            self.cl.login(config.IG_USERNAME, config.IG_PASSWORD, verification_code=code)
        config.IG_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.cl.dump_settings(config.IG_SESSION_FILE)

    def post_image(self, path, caption):
        return self.cl.photo_upload(path, caption).code

    def post_reel(self, path, caption, cover=None):
        return self.cl.clip_upload(path, caption, thumbnail=cover).code


class GraphPoster:
    """Official Instagram API (Professional account).

    Tokens from "API setup with Instagram login" (start with IG...) use graph.instagram.com;
    Facebook-login tokens (EAA...) use graph.facebook.com.
    """

    def __init__(self):
        if not config.IG_ACCESS_TOKEN:
            raise RuntimeError("Instagram access token is required for the official API")
        host = "graph.instagram.com" if config.IG_ACCESS_TOKEN.startswith("IG") else "graph.facebook.com"
        self.instagram_login = host == "graph.instagram.com"
        self.api = f"https://{host}/{config.GRAPH_VERSION}"
        self._refresh_token()
        self.user_id = config.IG_USER_ID or self.whoami()["user_id"]

    def _get(self, path, **params):
        r = requests.get(f"{self.api}/{path}", params={**params, "access_token": config.IG_ACCESS_TOKEN}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Instagram API {path}: {r.text}")
        return r.json()

    def _post(self, path, **data):
        r = requests.post(f"{self.api}/{path}", data={**data, "access_token": config.IG_ACCESS_TOKEN}, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Instagram API {path}: {r.text}")
        return r.json()

    def whoami(self):
        """{'user_id': ..., 'username': ...} for the token's account."""
        if self.instagram_login:
            return self._get("me", fields="user_id,username")
        data = self._get(config.IG_USER_ID or "me", fields="id,username")
        return {"user_id": data["id"], "username": data.get("username", "")}

    def _refresh_token(self):
        """Long-lived Instagram tokens last 60 days; refresh weekly so they never expire."""
        if not self.instagram_login:
            return
        saved = config.load_settings()
        refreshed_at = float(saved.get("TOKEN_REFRESHED_AT") or 0)
        if not refreshed_at:
            # first use of this token: start its refresh clock
            saved["TOKEN_REFRESHED_AT"] = str(time.time())
            config.save_settings(saved)
            return
        if time.time() - refreshed_at < 7 * 86400:
            return
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": config.IG_ACCESS_TOKEN}, timeout=30)
        if r.ok and r.json().get("access_token"):
            saved.update(IG_ACCESS_TOKEN=r.json()["access_token"], TOKEN_REFRESHED_AT=str(time.time()))
            config.save_settings(saved)
            print("[poster] access token refreshed")
        else:
            print(f"[poster] token refresh failed: {r.text}")

    def _wait_and_publish(self, creation_id):
        for _ in range(60):
            status = self._get(creation_id, fields="status_code").get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise RuntimeError("Instagram failed to process the media")
            time.sleep(10)
        return self._post(f"{self.user_id}/media_publish", creation_id=creation_id)["id"]

    def post_image(self, path, caption):
        if config.PUBLIC_MEDIA_BASE_URL:
            # the image must be reachable at a public URL for photo posts
            creation = self._post(f"{self.user_id}/media", image_url=f"{config.PUBLIC_MEDIA_BASE_URL}/{path.name}",
                                  caption=caption)
            return self._wait_and_publish(creation["id"])
        # no public URL: upload the design as a short still reel (shows in the grid the same way)
        import reel

        video = reel.still_video(path, path.with_suffix(".mp4"))
        return self.post_reel(video, caption)

    def post_reel(self, path, caption, cover=None):
        # resumable upload sends the local file directly — no public URL needed
        creation = self._post(f"{self.user_id}/media", media_type="REELS",
                              upload_type="resumable", caption=caption, share_to_feed="true")
        data = path.read_bytes()
        r = requests.post(
            creation["uri"],
            headers={"Authorization": f"OAuth {config.IG_ACCESS_TOKEN}", "offset": "0", "file_size": str(len(data))},
            data=data, timeout=300,
        )
        if not r.ok:
            raise RuntimeError(f"Reel upload failed: {r.text}")
        return self._wait_and_publish(creation["id"])


def get_poster(ask_code=None):
    return GraphPoster() if config.IG_BACKEND == "graph" else InstagrapiPoster(ask_code)
