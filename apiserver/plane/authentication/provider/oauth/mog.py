# MOG OIDC provider — sign in with the Steam-canonical identity that
# the mog-platform website uses. Mirrors the shape of github.py /
# google.py but points at the OpenIddict server in mog-platform.
#
# The mog-platform side of this is:
#   - OpenIddict server registered at /connect/{authorize,token,userinfo}
#   - Plane registered as an OIDC client by the OpenIddictClientSeeder
#     when MOG_PLATFORM:Plane:* config values are set
#   - Claims returned: sub (Player.Id Guid), name, preferred_username,
#     plus DSN-gated github_login / github_org_member / github_teams
#     when the mog:github scope is requested.
#
# Plane CE doesn't ship a generic OIDC adapter today; this one is
# bespoke for the Mog-Deadlock fork. The shape is straight OAuth2 +
# userinfo since OpenIddict speaks both protocols.

import os
from datetime import datetime
from urllib.parse import urlencode

import pytz
import requests

from plane.authentication.adapter.oauth import OauthAdapter
from plane.license.utils.instance_value import get_configuration_value
from plane.authentication.adapter.error import (
    AuthenticationException,
    AUTHENTICATION_ERROR_CODES,
)


class MogOAuthProvider(OauthAdapter):
    provider = "mog"
    # Default scopes — openid + profile + email gives us sub + name +
    # preferred_username; mog:github surfaces the GitHub-org claims
    # that the platform-side OpenIddictClaimsBuilder sets.
    scope = "openid profile email mog:github offline_access"

    def __init__(self, request, code=None, state=None, callback=None):
        (
            MOG_CLIENT_ID,
            MOG_CLIENT_SECRET,
            MOG_AUTHORIZE_URL,
            MOG_TOKEN_URL,
            MOG_USERINFO_URL,
        ) = get_configuration_value(
            [
                {
                    "key": "MOG_CLIENT_ID",
                    "default": os.environ.get("MOG_CLIENT_ID"),
                },
                {
                    "key": "MOG_CLIENT_SECRET",
                    "default": os.environ.get("MOG_CLIENT_SECRET"),
                },
                {
                    "key": "MOG_AUTHORIZE_URL",
                    "default": os.environ.get(
                        "MOG_AUTHORIZE_URL",
                        "https://mogdl.com/connect/authorize",
                    ),
                },
                {
                    "key": "MOG_TOKEN_URL",
                    "default": os.environ.get(
                        "MOG_TOKEN_URL",
                        "https://mogdl.com/connect/token",
                    ),
                },
                {
                    "key": "MOG_USERINFO_URL",
                    "default": os.environ.get(
                        "MOG_USERINFO_URL",
                        "https://mogdl.com/connect/userinfo",
                    ),
                },
            ]
        )

        if not (MOG_CLIENT_ID and MOG_CLIENT_SECRET):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["MOG_NOT_CONFIGURED"],
                error_message="MOG_NOT_CONFIGURED",
            )

        client_id = MOG_CLIENT_ID
        client_secret = MOG_CLIENT_SECRET
        self.token_url = MOG_TOKEN_URL
        self.userinfo_url = MOG_USERINFO_URL

        redirect_uri = (
            f"""{"https" if request.is_secure() else "http"}"""
            f"""://{request.get_host()}/auth/mog/callback/"""
        )
        url_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
        }
        auth_url = f"{MOG_AUTHORIZE_URL}?{urlencode(url_params)}"

        super().__init__(
            request,
            self.provider,
            client_id,
            self.scope,
            redirect_uri,
            auth_url,
            self.token_url,
            self.userinfo_url,
            client_secret,
            code,
            callback=callback,
        )

    def set_token_data(self):
        # OpenIddict's token endpoint is RFC 6749 vanilla — POST
        # form-encoded with grant_type=authorization_code.
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": self.code,
            "redirect_uri": self.redirect_uri,
        }
        token_response = self.get_user_token(
            data=data, headers={"Accept": "application/json"}
        )

        # OpenIddict returns expires_in (seconds, integer). Some OIDC
        # servers omit it on refresh; fall back to None and let the
        # client re-fetch when the access token actually fails.
        expires_in = token_response.get("expires_in")
        access_token_expires_at = (
            datetime.now(tz=pytz.utc) + (datetime.utcfromtimestamp(0)
            if expires_in is None
            else datetime.utcfromtimestamp(int(expires_in)) - datetime.utcfromtimestamp(0))
        ) if expires_in else None

        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token", None),
                "access_token_expired_at": access_token_expires_at,
                "refresh_token_expired_at": None,
                "id_token": token_response.get("id_token", ""),
            }
        )

    def authenticate(self):
        user = super().authenticate()
        self.sync_mog_profile(user)
        return user

    def sync_mog_profile(self, user):
        mog_user = self.user_data.get("user", {})
        display_name = mog_user.get("display_name", "")
        avatar = mog_user.get("avatar", "")

        changed_fields = []
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed_fields.append("display_name")

        first_name = mog_user.get("first_name", "")
        if user.first_name != first_name:
            user.first_name = first_name
            changed_fields.append("first_name")

        last_name = mog_user.get("last_name", "")
        if user.last_name != last_name:
            user.last_name = last_name
            changed_fields.append("last_name")

        if avatar and user.avatar != avatar:
            user.avatar = avatar
            changed_fields.append("avatar")

        if avatar and user.avatar_asset_id is not None:
            user.avatar_asset_id = None
            changed_fields.append("avatar_asset")

        if changed_fields:
            user.save(update_fields=changed_fields)

    def set_user_data(self):
        # OpenIddict's userinfo endpoint returns the OIDC-standard
        # claims plus our custom mog:github extras when the scope was
        # requested. Map to Plane's normalized user shape.
        user_info_response = self.get_user_response()

        sub = user_info_response.get("sub")
        if not sub:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["MOG_OAUTH_PROVIDER_ERROR"],
                error_message="MOG_OAUTH_PROVIDER_ERROR",
            )

        # Plane requires an email to find/create users. mog-platform
        # may or may not surface one (Steam profile email is opt-in).
        # When absent, synthesize a stable placeholder so the same
        # MOG identity always resolves to the same Plane User.
        email = user_info_response.get("email")
        if not email:
            email = f"{sub}@mog-deadlock.local"
        email = email.lower()

        display_name = (
            user_info_response.get("name")
            or user_info_response.get("display_name")
            or user_info_response.get("steam_display_name")
            or user_info_response.get("preferred_username")
            or sub
        )

        # Best-effort first/last split for Plane's profile shape.
        first_name = display_name.split(" ", 1)[0] if display_name else ""
        last_name = display_name.split(" ", 1)[1] if display_name and " " in display_name else ""

        super().set_user_data(
            {
                "email": email,
                "user": {
                    "provider_id": sub,
                    "email": email,
                    "avatar": (
                        user_info_response.get("picture")
                        or user_info_response.get("avatar_url")
                        or user_info_response.get("steam_avatar_url")
                        or user_info_response.get("avatarfull")
                        or user_info_response.get("avatarmedium")
                        or user_info_response.get("avatar")
                        or ""
                    ),
                    "display_name": display_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_password_autoset": True,
                },
            }
        )
