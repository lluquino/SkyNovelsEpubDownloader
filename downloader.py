import logging
import requests
import os
import re
import html
from ebooklib import epub
import markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

NOVEL_ID = 1
BASE_API = "https://www.skynovels.net/api"
IMAGE_API = "https://api.skynovels.net/api/get-image"

OUTPUT_DIR = "epubs"
IMG_DIR = os.path.join(OUTPUT_DIR, "images")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)


# -------------------------
# Utils
# -------------------------

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_media_type(filename):
    ext = filename.lower().split(".")[-1]

    if ext in ["jpg", "jpeg"]:
        return "image/jpeg"
    elif ext == "png":
        return "image/png"
    elif ext == "webp":
        return "image/webp"
    elif ext == "gif":
        return "image/gif"
    else:
        return "image/jpeg"


def normalize_image_url(url):
    if "pbs.twimg.com" in url:
        url = re.sub(r'name=\w+', 'name=orig', url)
    return url


# -------------------------
# API Calls
# -------------------------

def fetch_novel():
    url = f"{BASE_API}/novel/{NOVEL_ID}/reading"
    logging.info("Fetching novel metadata")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()["novel"][0]


def fetch_chapter(chapter_id):
    url = f"{BASE_API}/novel-chapter/{chapter_id}"
    logging.info(f"Fetching chapter {chapter_id}")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()["chapter"][0]


# -------------------------
# Images
# -------------------------

def download_image(url, chapter_id):
    try:
        url = html.unescape(url)
        url = normalize_image_url(url)

        base = url.split("/")[-1].split("?")[0]

        if "." not in base:
            base += ".jpg"

        filename = f"{chapter_id}_{base}"
        path = os.path.join(IMG_DIR, filename)

        if not os.path.exists(path):
            logging.info(f"Downloading image: {url}")

            r = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.skynovels.net/"
                }
            )

            r.raise_for_status()

            with open(path, "wb") as f:
                f.write(r.content)

        return filename

    except Exception as e:
        logging.error(f"Image error: {e} | URL: {url}")
        return None


def process_images(book, html_content, chapter_id):
    def replace(match):
        url = html.unescape(match.group(1))

        filename = download_image(url, chapter_id)
        if not filename:
            return ""

        path = os.path.join(IMG_DIR, filename)

        with open(path, "rb") as f:
            content = f.read()

        media_type = get_media_type(filename)
        epub_path = f"images/{filename}"

        img_item = epub.EpubItem(
            uid=f"img_{chapter_id}_{filename}",
            file_name=epub_path,
            media_type=media_type,
            content=content
        )

        book.add_item(img_item)

        # reemplazo limpio del tag completo
        return f'<img src="{epub_path}" />'

    return re.sub(
        r'<img[^>]+src="([^"]+)"[^>]*>',
        replace,
        html_content
    )


# -------------------------
# Content processing
# -------------------------

def markdown_to_html(md_text):
    html_content = markdown.markdown(md_text)

    return html_content


# -------------------------
# EPUB builder
# -------------------------

def create_book(novel, volume):
    book = epub.EpubBook()

    title = f"{novel['nvl_title']} - {volume['vlm_title']}"

    book.set_identifier(f"{NOVEL_ID}-{volume['id']}")
    book.set_title(title)
    book.set_language("es")

    book.add_author(novel.get("nvl_writer", "Unknown"))

    book.add_metadata("DC", "description", novel.get("nvl_content", ""))
    book.add_metadata("DC", "date", novel.get("createdAt", ""))

    if novel.get("nvl_titlealternative"):
        book.add_metadata("DC", "subject", novel["nvl_titlealternative"])

    # portada
    if novel.get("image"):
        try:
            url = f"{IMAGE_API}/{novel['image']}/novels/false"
            logging.info(f"Downloading cover: {url}")

            r = requests.get(url)
            r.raise_for_status()

            book.set_cover("cover.jpg", r.content)

        except Exception as e:
            logging.error(f"Cover error: {e}")

    return book


# -------------------------
# Main
# -------------------------

def main():
    novel = fetch_novel()

    for volume in novel["volumes"]:
        logging.info(f"Processing volume: {volume['vlm_title']}")

        book = create_book(novel, volume)

        chapters_epub = []

        for ch in volume["chapters"]:
            ch_data = fetch_chapter(ch["id"])

            title = f"Capítulo {ch_data['chp_number']}: {ch_data['chp_title']}"
            logging.info(f"Processing chapter: {title}")

            md_content = ch_data["chp_content"]

            html_content = markdown_to_html(md_content)
            html_content = process_images(book, html_content, ch_data["id"])

            chapter = epub.EpubHtml(
                title=title,
                file_name=f"chap_{ch_data['id']}.xhtml",
                lang="es"
            )

            chapter.content = f"<h1>{title}</h1>{html_content}"

            book.add_item(chapter)
            chapters_epub.append(chapter)

        # TOC
        book.toc = tuple(chapters_epub)

        # navegación
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # spine
        book.spine = ["nav"] + chapters_epub

        filename = sanitize_filename(
            f"{novel['nvl_title']} - {volume['vlm_title']}"
        ) + ".epub"

        path = os.path.join(OUTPUT_DIR, filename)

        logging.info(f"Writing EPUB: {path}")
        epub.write_epub(path, book)

    logging.info("DONE")


if __name__ == "__main__":
    main()