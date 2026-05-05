"""Telegram bot que recibe links de Reels de Instagram y devuelve el número de views."""

import logging
import os
import re
import time

import instaloader
import telebot

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Falta la variable de entorno BOT_TOKEN")

IG_USER = os.environ.get("IG_USER")
IG_PASS = os.environ.get("IG_PASS")
IG_SESSION_FILE = os.environ.get("IG_SESSION_FILE")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ig-views-bot")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

loader = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    quiet=True,
)

if IG_SESSION_FILE and IG_USER and os.path.exists(IG_SESSION_FILE):
    try:
        loader.load_session_from_file(IG_USER, IG_SESSION_FILE)
        log.info("Sesión de Instagram cargada desde archivo para %s", IG_USER)
    except Exception as exc:
        log.warning("No pude cargar la sesión: %s", exc)
elif IG_USER and IG_PASS:
    try:
        loader.login(IG_USER, IG_PASS)
        log.info("Login de Instagram OK para %s", IG_USER)
    except Exception as exc:
        log.warning("No pude iniciar sesión en Instagram: %s", exc)

SHORTCODE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def pretty(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return str(n)


def fetch_views(shortcode: str) -> tuple[int | None, str]:
    """Devuelve (views, mensaje_de_error). views=None si no se pudo obtener."""
    try:
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
    except instaloader.exceptions.LoginRequiredException:
        return None, "requiere login (define IG_USER/IG_PASS)"
    except instaloader.exceptions.QueryReturnedNotFoundException:
        return None, "no encontrado"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    if not post.is_video:
        return None, "no es un video/reel"

    play_count = getattr(post, "video_play_count", None)
    view_count = post.video_view_count
    candidates = [c for c in (play_count, view_count) if c is not None]
    if not candidates:
        return None, "Instagram no expuso el contador"
    return int(max(candidates)), ""


@bot.message_handler(commands=["start", "help"])
def cmd_start(message: telebot.types.Message) -> None:
    bot.reply_to(
        message,
        (
            "👋 Mándame uno o varios links de <b>Reels de Instagram</b> "
            "(uno por línea o separados por espacios) y te respondo con las views de cada uno.\n\n"
            "Ejemplo:\n"
            "<code>https://www.instagram.com/reel/Cxxxxxxxx/\n"
            "https://www.instagram.com/reel/Cyyyyyyyy/</code>"
        ),
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_links(message: telebot.types.Message) -> None:
    text = message.text or ""
    shortcodes: list[str] = []
    seen: set[str] = set()
    for match in SHORTCODE_RE.finditer(text):
        sc = match.group(1)
        if sc not in seen:
            seen.add(sc)
            shortcodes.append(sc)

    if not shortcodes:
        bot.reply_to(
            message,
            "❌ No encontré ningún link de Instagram. Mándame URLs tipo "
            "<code>instagram.com/reel/...</code>",
        )
        return

    status = bot.reply_to(message, f"⏳ Procesando {len(shortcodes)} link(s)…")

    lines: list[str] = []
    total = 0
    ok = 0
    for i, sc in enumerate(shortcodes, 1):
        url = f"https://www.instagram.com/reel/{sc}/"
        views, err = fetch_views(sc)
        if views is None:
            lines.append(f"{i}. <a href=\"{url}\">{sc}</a>\n   ⚠️ {err}")
        else:
            lines.append(
                f"{i}. <a href=\"{url}\">{sc}</a>\n"
                f"   👁️ <b>{views:,}</b> views ({pretty(views)})"
            )
            total += views
            ok += 1
        if i < len(shortcodes):
            time.sleep(1.2)

    if ok > 1:
        lines.append(
            f"\n📊 <b>Total:</b> {total:,} views ({pretty(total)}) en {ok} reel(s)"
        )

    reply = "\n".join(lines)
    try:
        bot.edit_message_text(
            reply,
            chat_id=status.chat.id,
            message_id=status.message_id,
            disable_web_page_preview=True,
        )
    except Exception:
        bot.reply_to(message, reply, disable_web_page_preview=True)


if __name__ == "__main__":
    log.info("Bot iniciado")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
