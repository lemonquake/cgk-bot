"""
Dynamic text hydration and broadcast message state.
Created by Aljay Leodones for CGK Linens.

Any moderator-authored text (onboarding welcome posts, embed broadcasts, plain
messages) passes through `resolve_text` so live placeholders such as
`{server_name}` or `{onboarding_channel}` are substituted before delivery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

import discord

from config import BRAND_NAME, COLOR_BRAND
from utils import embed_builder

# Documented placeholders, shown to moderators inside the composer modals.
PLACEHOLDER_HELP = (
    "{user_mention} · {user_name} · {server_name} · {member_count} · "
    "{date_now} · {time_now} · {brand} · {onboarding_channel} · "
    "{introductions_channel} · {welcome_channel}"
)

# Payload schema version. Stored with every saved template and draft so an
# older row can still be recognised (and migrated) by a future build.
PAYLOAD_VERSION = 2

# Field ceilings, kept a little under Discord's own limits.
MAX_CONTENT_LENGTH = 1900
MAX_TITLE_LENGTH = 250
MAX_DESCRIPTION_LENGTH = 3800
MAX_IMAGE_URL_LENGTH = 500


def normalize_color(raw: Any) -> int:
    """Accepts `#1B365D`, `1B365D`, `0x1B365D` or an int; brand navy on failure."""
    if isinstance(raw, bool) or raw is None:
        return COLOR_BRAND
    if isinstance(raw, int):
        value = raw
    else:
        cleaned = str(raw).strip().lstrip("#")
        if cleaned[:2].lower() == "0x":
            cleaned = cleaned[2:]
        try:
            value = int(cleaned, 16)
        except ValueError:
            return COLOR_BRAND
    return value if 0 <= value <= 0xFFFFFF else COLOR_BRAND


def normalize_url(raw: Any) -> Optional[str]:
    """Keeps only `http(s)` links - Discord silently drops anything else."""
    candidate = str(raw or "").strip()
    if not candidate or not candidate.lower().startswith(("http://", "https://")):
        return None
    return candidate[:MAX_IMAGE_URL_LENGTH]


def clean_text(raw: Any, limit: int) -> Optional[str]:
    """Trims a stored or typed field to something Discord will accept."""
    if raw is None:
        return None
    text = str(raw).replace("\r\n", "\n").strip()
    return text[:limit] or None


def _optional_id(raw: Any) -> Optional[int]:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_text(
    text: Optional[str],
    *,
    member: Optional[discord.Member] = None,
    guild: Optional[discord.Guild] = None,
    channels: Optional[dict[str, int | None]] = None,
) -> Optional[str]:
    """Replaces every supported placeholder with live server data."""
    if not text or "{" not in text:
        return text

    guild = guild or (member.guild if member else None)
    now = datetime.now(embed_builder.display_timezone())
    channels = channels or {}

    def channel_token(key: str) -> str:
        channel_id = channels.get(key)
        return f"<#{channel_id}>" if channel_id else f"#{key.replace('_', '-')}"

    replacements = {
        "{user_mention}": member.mention if member else "(member mention)",
        "{user_name}": member.display_name if member else "(member name)",
        "{server_name}": guild.name if guild else "(server name)",
        "{member_count}": f"{guild.member_count:,}" if guild and guild.member_count else "0",
        "{date_now}": now.strftime("%d/%m/%Y"),
        "{time_now}": now.strftime("%I:%M %p"),
        "{brand}": BRAND_NAME,
        "{onboarding_channel}": channel_token("onboarding"),
        "{introductions_channel}": channel_token("introductions"),
        "{welcome_channel}": channel_token("welcome"),
    }

    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


class EmbedScript:
    """
    Serializable state for one moderator-composed broadcast.

    Holds the plain message content, a single branded embed and the target
    channels, and can render itself for either a live send or a preview.
    """

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.content: Optional[str] = None
        self.title: Optional[str] = None
        self.description: Optional[str] = None
        self.image_url: Optional[str] = None
        self.color: int = COLOR_BRAND
        # The server icon in the embed's top-right corner. On by default so
        # nothing that was already saved changes look, but a message with its
        # own branded banner usually reads better without it.
        self.show_icon: bool = True
        self.channel_ids: list[int] = []
        # Set while the draft is linked to a stored template.
        self.template_id: Optional[int] = None
        self.template_name: Optional[str] = None

    @property
    def is_blank(self) -> bool:
        """True while there is nothing worth previewing, saving or sending."""
        return not (self.content or self.title or self.description or self.image_url)

    @property
    def has_embed(self) -> bool:
        return bool(self.title or self.description or self.image_url)

    # ── rendering ─────────────────────────────────────────────
    def render_embed(
        self,
        *,
        guild: Optional[discord.Guild] = None,
        channels: Optional[dict[str, int | None]] = None,
        resolve: bool = True,
    ) -> Optional[discord.Embed]:
        """
        Builds the branded embed exactly as Discord will show it.

        `resolve=False` leaves the placeholders as the moderator typed them,
        which is what the Embed Studio wants while a draft is still being
        written — the live substitution belongs to the publish preview.
        """
        if not self.has_embed:
            return None

        def text(value: Optional[str]) -> Optional[str]:
            if not resolve:
                return value
            return resolve_text(value, guild=guild, channels=channels)

        embed = embed_builder.base_embed(
            title=text(self.title),
            description=text(self.description),
            color=self.color,
        )
        if self.image_url:
            embed.set_image(url=self.image_url)
        if self.show_icon and guild and guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    def render_content(
        self,
        *,
        guild: Optional[discord.Guild] = None,
        channels: Optional[dict[str, int | None]] = None,
    ) -> Optional[str]:
        return resolve_text(self.content, guild=guild, channels=channels)

    # ── serialization ─────────────────────────────────────────
    def to_payload(self) -> dict[str, Any]:
        """
        The message itself, ready to be stored as a template.

        Deliberately excludes the author and the target channels: a template
        is reusable content, not a record of one particular send.
        """
        return {
            "version": PAYLOAD_VERSION,
            "content": self.content,
            "title": self.title,
            "description": self.description,
            "image_url": self.image_url,
            "color": self.color,
            "show_icon": self.show_icon,
        }

    def apply_payload(self, payload: Mapping[str, Any]) -> "EmbedScript":
        """
        Loads a stored payload, sanitising every field on the way in.

        Nothing here trusts the row: an oversized description, a `javascript:`
        image URL or a nonsense colour is corrected rather than breaking the
        composer or being rejected later by Discord.
        """
        self.content = clean_text(payload.get("content"), MAX_CONTENT_LENGTH)
        self.title = clean_text(payload.get("title"), MAX_TITLE_LENGTH)
        self.description = clean_text(
            payload.get("description"), MAX_DESCRIPTION_LENGTH
        )
        self.image_url = normalize_url(payload.get("image_url"))
        self.color = normalize_color(payload.get("color"))
        # Templates saved before the icon became a choice have no key at all,
        # and those were all published with the icon showing.
        self.show_icon = bool(payload.get("show_icon", True))
        return self

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, user_id: int
    ) -> "EmbedScript":
        return cls(user_id).apply_payload(payload)

    def to_draft_payload(self) -> dict[str, Any]:
        """Payload plus the template link, for the auto-saved working draft."""
        payload = self.to_payload()
        payload["template_id"] = self.template_id
        payload["template_name"] = self.template_name
        return payload

    def apply_draft_payload(self, payload: Mapping[str, Any]) -> "EmbedScript":
        self.apply_payload(payload)
        self.template_id = _optional_id(payload.get("template_id"))
        self.template_name = clean_text(payload.get("template_name"), 100)
        if self.template_id is None:
            self.template_name = None
        return self

    def clone(self, *, user_id: Optional[int] = None) -> "EmbedScript":
        """Independent copy, so a preview or a send can never mutate the draft."""
        duplicate = EmbedScript(self.user_id if user_id is None else user_id)
        duplicate.apply_draft_payload(self.to_draft_payload())
        duplicate.channel_ids = list(self.channel_ids)
        return duplicate

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_draft_payload()
        payload["user_id"] = self.user_id
        payload["target_channel_ids"] = list(self.channel_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EmbedScript":
        script = cls(_optional_id(payload.get("user_id")) or 0)
        script.apply_draft_payload(payload)
        script.channel_ids = [
            channel_id
            for channel_id in (
                _optional_id(value) for value in payload.get("target_channel_ids", [])
            )
            if channel_id is not None
        ]
        return script
