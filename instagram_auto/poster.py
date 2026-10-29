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
    def __init__(self):
        if not (config.IG_ACCESS_TOKEN and config.IG_USER_ID):
            raise RuntimeError("IG_ACCESS_TOKEN / IG_USER_ID are required for IG_BACKEND=graph")
        self.api = f"https://graph.facebook.com/{config.GRAPH_VERSION}"

    def _post(self, path, **data):
        r = requests.post(f"{self.api}/{path}", data={**data, "access_token": config.IG_ACCESS_TOKEN}, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Graph API {path}: {r.text}")
        return r.json()

    def _wait_and_publish(self, creation_id):
        for _ in range(60):
            status = requests.get(
                f"{self.api}/{creation_id}",
                params={"fields": "status_code", "access_token": config.IG_ACCESS_TOKEN}, timeout=30,
            ).json().get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise RuntimeError("Instagram failed to process the media")
            time.sleep(10)
        return self._post(f"{config.IG_USER_ID}/media_publish", creation_id=creation_id)["id"]

    def post_image(self, path, caption):
        if not config.PUBLIC_MEDIA_BASE_URL:
            raise RuntimeError("Graph API feed posts need PUBLIC_MEDIA_BASE_URL (a public URL serving output/ media)")
        url = f"{config.PUBLIC_MEDIA_BASE_URL}/{path.name}"
        # the site may still be deploying the freshly committed image
        for _ in range(30):
            if requests.head(url, timeout=15).ok:
                break
            time.sleep(20)
        creation = self._post(f"{config.IG_USER_ID}/media", image_url=url, caption=caption)
        return self._wait_and_publish(creation["id"])

    def post_reel(self, path, caption, cover=None):
        # resumable upload sends the local file directly — no public URL needed
        creation = self._post(f"{config.IG_USER_ID}/media", media_type="REELS",
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
