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

    def post_album(self, paths, caption):
        if len(paths) == 1:
            return self.post_image(paths[0], caption)
        return self.cl.album_upload(paths, caption).code


def mask(text):
    """Never show a whole token: keep its first 4 characters."""
    token = config.IG_ACCESS_TOKEN
    text = str(text)
    return text.replace(token, token[:4] + "…") if token else text


class MetaAPIError(RuntimeError):
    """A Graph API error, shown as Meta's own message and code."""

    PERMISSION_CODES = {10, 200}

    def __init__(self, path, response):
        try:
            err = response.json().get("error", {})
        except ValueError:
            err = {}
        self.code = err.get("code")
        message = err.get("message") or response.text
        text = f"Meta API 오류 ({path}) code {self.code}: {message}"
        if self.code in self.PERMISSION_CODES or (isinstance(self.code, int) and 200 <= self.code <= 299):
            text += "\n→ Meta 앱에서 instagram_content_publish 권한과 Instagram Tester 수락을 확인하세요."
        super().__init__(mask(text))


class GraphPoster:
    """Official Instagram API (Professional account), chosen by the token's prefix:

    IG...  Instagram-login token -> graph.instagram.com, long-lived token refreshed weekly
    EAA... Facebook / unified-login token (e.g. a never-expiring system user token)
           -> graph.facebook.com, no refresh
    """

    def __init__(self):
        token = config.IG_ACCESS_TOKEN
        if not token:
            raise RuntimeError("인스타 액세스 토큰(IG... 또는 EAA...)을 넣어 주세요.")
        self.instagram_login = token.startswith("IG")
        if self.instagram_login:
            self.api = f"https://graph.instagram.com/{config.GRAPH_VERSION}"
        else:
            self.api = f"https://graph.facebook.com/{config.FB_GRAPH_VERSION}"
        print(f"[poster] token {token[:4]}… -> {self.api.split('/')[2]}")
        self._refresh_token()
        self.user_id = config.IG_USER_ID or self.whoami()["user_id"]

    def _request(self, method, path, timeout=60, **kwargs):
        url = path if path.startswith("https://") else f"{self.api}/{path}"
        try:
            r = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            raise RuntimeError(mask(f"Meta API 연결 실패 ({path}): {e}")) from None
        if not r.ok:
            raise MetaAPIError(path, r)
        return r.json()

    def _get(self, path, **params):
        return self._request("GET", path, timeout=30, params={**params, "access_token": config.IG_ACCESS_TOKEN})

    def _post(self, path, **data):
        return self._request("POST", path, data={**data, "access_token": config.IG_ACCESS_TOKEN})

    def whoami(self):
        """{'user_id': ..., 'username': ...} for the token's Instagram account."""
        if self.instagram_login:
            return self._get("me", fields="user_id,username")
        if config.IG_USER_ID:
            data = self._get(config.IG_USER_ID, fields="id,username")
            return {"user_id": data["id"], "username": data.get("username", "")}
        account = self._linked_instagram_account()
        # remember it so later rounds skip the lookup
        saved = config.load_settings()
        saved["IG_USER_ID"] = account["id"]
        config.save_settings(saved)
        print(f"[poster] found Instagram business account {account['id']} (@{account.get('username', '')})")
        return {"user_id": account["id"], "username": account.get("username", "")}

    def _linked_instagram_account(self):
        """EAA token: the Instagram business account connected to the token's Facebook Page(s)."""
        field = "instagram_business_account{id,username}"
        try:
            pages = self._get("me/accounts", fields=f"name,{field}").get("data", [])
        except RuntimeError:
            try:
                pages = [self._get("me", fields=f"name,{field}")]  # a Page token: /me is the Page itself
            except RuntimeError:
                pages = []
        for page in pages:
            if page.get("instagram_business_account"):
                return page["instagram_business_account"]
        names = ", ".join(p.get("name", "?") for p in pages) or "없음"
        raise RuntimeError(
            f"이 토큰으로 연결된 인스타 비즈니스 계정을 자동으로 찾지 못했습니다 (찾은 페이스북 페이지: {names}).\n"
            "설정의 '인스타 비즈니스 계정 ID' 칸에 숫자 ID(예: 1784...)를 직접 넣어 주세요.")

    def _refresh_token(self):
        """IG long-lived tokens last 60 days; refresh weekly. EAA tokens are skipped (system user tokens don't expire)."""
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
        try:
            data = self._request("GET", "https://graph.instagram.com/refresh_access_token", timeout=30,
                                 params={"grant_type": "ig_refresh_token", "access_token": config.IG_ACCESS_TOKEN})
        except RuntimeError as e:
            print(f"[poster] token refresh failed: {e}")
            return
        if data.get("access_token"):
            saved.update(IG_ACCESS_TOKEN=data["access_token"], TOKEN_REFRESHED_AT=str(time.time()))
            config.save_settings(saved)
            print("[poster] access token refreshed")

    def _wait_until_ready(self, container_id):
        for _ in range(60):
            status = self._get(container_id, fields="status_code").get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram이 미디어 처리에 실패했습니다 (status {status}).")
            time.sleep(5)
        raise RuntimeError("Instagram 미디어 처리가 5분 안에 끝나지 않았습니다.")

    def _publish(self, container_id):
        self._wait_until_ready(container_id)
        return self._post(f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def _public_url(self, path):
        return f"{config.PUBLIC_MEDIA_BASE_URL}/{path.name}" if config.PUBLIC_MEDIA_BASE_URL else None

    def _video_container(self, path, **fields):
        """Container for a video: by public video_url if we have one, else resumable upload of the local file."""
        url = self._public_url(path)
        if url:
            return self._post(f"{self.user_id}/media", video_url=url, **fields)["id"]
        container = self._post(f"{self.user_id}/media", upload_type="resumable", **fields)
        size = path.stat().st_size
        with open(path, "rb") as f:
            self._request("POST", container["uri"], timeout=300, data=f, headers={
                "Authorization": f"OAuth {config.IG_ACCESS_TOKEN}", "offset": "0", "file_size": str(size)})
        return container["id"]

    def post_image(self, path, caption):
        url = self._public_url(path)
        if url:
            return self._publish(self._post(f"{self.user_id}/media", image_url=url, caption=caption)["id"])
        # photos are only accepted by public URL: post the design as a short still reel instead
        import reel

        return self.post_reel(reel.still_video(path, path.with_suffix(".mp4")), caption)

    def post_reel(self, path, caption, cover=None):
        return self._publish(self._video_container(path, media_type="REELS", caption=caption, share_to_feed="true"))

    def post_album(self, paths, caption):
        """A carousel of the slide images (or a single post for one image)."""
        if len(paths) == 1:
            return self.post_image(paths[0], caption)
        if config.PUBLIC_MEDIA_BASE_URL:
            return self.post_carousel(paths, caption)
        # photos are only accepted by public URL: upload each slide as a short still video instead
        import reel

        videos = [reel.still_video(p, p.with_suffix(".mp4"), seconds=5) for p in paths]
        try:
            return self.post_carousel(videos, caption)
        except RuntimeError as e:
            print(f"[poster] carousel failed ({e}) — posting the cover only")
            return self.post_image(paths[0], caption)

    def post_carousel(self, paths, caption):
        """2-10 images/videos as one carousel post (images need PUBLIC_MEDIA_BASE_URL)."""
        children = []
        for path in paths:
            if path.suffix.lower() in (".mp4", ".mov"):
                child = self._video_container(path, media_type="VIDEO", is_carousel_item="true")
            else:
                url = self._public_url(path)
                if not url:
                    raise RuntimeError("캐러셀 사진은 공개 URL이 필요합니다 (PUBLIC_MEDIA_BASE_URL).")
                child = self._post(f"{self.user_id}/media", image_url=url, is_carousel_item="true")["id"]
            self._wait_until_ready(child)
            children.append(child)
        carousel = self._post(f"{self.user_id}/media", media_type="CAROUSEL",
                              children=",".join(children), caption=caption)["id"]
        return self._publish(carousel)


def get_poster(ask_code=None):
    return GraphPoster() if config.IG_BACKEND == "graph" else InstagrapiPoster(ask_code)
