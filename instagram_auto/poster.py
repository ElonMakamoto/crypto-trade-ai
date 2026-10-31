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
        if "access blocked" in message.lower():
            # Meta blocks this one Instagram account, not the token (other channels with the same token still work)
            text += ("\n→ Meta가 이 인스타 계정의 API 사용을 막았습니다. 휴대폰 인스타 앱에서 이 계정으로 로그인해 "
                     "보안 확인·경고(설정 → 계정 상태)를 처리하고, 프로페셔널 계정인지와 Facebook 페이지 연결을 확인하세요. "
                     "Meta 앱이 개발 모드면 이 계정을 앱 역할(테스터)에 추가하고 수락해야 합니다.")
        elif self.code in self.PERMISSION_CODES or (isinstance(self.code, int) and 200 <= self.code <= 299):
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
        if self.instagram_login:
            self.user_id = self._own_account()
        else:
            self.user_id = config.IG_USER_ID or self.whoami()["user_id"]

    def _own_account(self):
        """An Instagram-login token can only post to the account it was made for (any other ID: 'API access blocked')."""
        me = self._get("me", fields="id,user_id,username")
        if config.IG_USER_ID and config.IG_USER_ID not in (str(me.get("user_id")), str(me.get("id"))):
            raise RuntimeError(
                f"이 IG 토큰은 @{me.get('username', '?')} (ID {me.get('user_id')}) 계정 전용이라 "
                f"설정한 계정 ID {config.IG_USER_ID} 에는 올릴 수 없습니다.\n"
                f"→ 설정 → 이 채널 탭의 '이 채널 전용 Meta 토큰' 칸에 그 계정으로 로그인해서 받은 토큰을 넣거나, "
                f"모든 계정에 쓸 수 있는 EAA 토큰(시스템 사용자 토큰)을 공통 토큰으로 쓰세요.")
        return str(me.get("user_id") or me.get("id"))

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
            try:
                data = self._get(config.IG_USER_ID, fields="id,username")
            except MetaAPIError as e:
                if e.code != 100:
                    raise
                raise RuntimeError(self._no_access_help(config.IG_USER_ID)) from None
            return {"user_id": data["id"], "username": data.get("username", "")}
        account = self._linked_instagram_account()
        # remember it so later rounds skip the lookup
        config.remember("IG_USER_ID", account["id"])
        print(f"[poster] found Instagram business account {account['id']} (@{account.get('username', '')})")
        return {"user_id": account["id"], "username": account.get("username", "")}

    def _pages(self):
        """Facebook Pages this token can use, with their linked Instagram account (if any)."""
        field = "instagram_business_account{id,username}"
        try:
            return self._get("me/accounts", fields=f"name,{field}", limit=100).get("data", [])
        except RuntimeError:
            try:
                return [self._get("me", fields=f"name,{field}")]  # a Page token: /me is the Page itself
            except RuntimeError:
                return []

    def _no_access_help(self, ig_id):
        """Why an account id can't be used, with the accounts this token CAN reach."""
        reachable = [f"@{p['instagram_business_account'].get('username', '?')} "
                     f"(ID {p['instagram_business_account']['id']}, 페이지 '{p.get('name', '?')}')"
                     for p in self._pages() if p.get("instagram_business_account")]
        listing = "\n".join(f"  • {r}" for r in reachable) or "  (없음)"
        return (f"인스타 계정 ID {ig_id} 에 이 Meta 토큰으로 접근할 수 없습니다.\n\n"
                f"이 토큰이 지금 접근할 수 있는 인스타 계정:\n{listing}\n\n"
                "목록에 없다면 Meta 비즈니스 설정에서 이 계정(과 연결된 페이스북 페이지)을 토큰의 시스템 사용자에게 "
                "자산으로 할당해 주세요. 자세한 방법은 '인스타 토큰 받는 법' 안내를 보세요.")

    def _linked_instagram_account(self):
        """EAA token: the Instagram business account connected to the token's Facebook Page(s)."""
        pages = self._pages()
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
        channel_token = config.ACTIVE_CHANNEL and config.load_channel(config.ACTIVE_CHANNEL, saved)["CHANNEL_TOKEN"]
        # a channel's own token keeps its own refresh clock
        clock = f"TOKEN_REFRESHED_AT_{config.ACTIVE_CHANNEL}" if channel_token else "TOKEN_REFRESHED_AT"
        refreshed_at = float(saved.get(clock) or 0)
        if not refreshed_at:
            # first use of this token: start its refresh clock
            saved[clock] = str(time.time())
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
            saved[clock] = str(time.time())
            if not channel_token:
                saved["IG_ACCESS_TOKEN"] = data["access_token"]
            config.save_settings(saved)
            if channel_token:  # the channel's own token is the one that was refreshed
                config.remember("CHANNEL_TOKEN", data["access_token"])
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
