#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = ["playwright>=1.48.0", "beautifulsoup4>=4.12.0"]
# ///
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time

IDR_URL = "https://idr.openmicroscopy.org/"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(IDR_URL)
        time.sleep(5)  # Wait for the page to load and render thumbnails.
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    study_thumbs = [
        el for el in soup.select(".studyThumb") if el.select_one(".studyThumbLink")
    ]
    if not study_thumbs:
        raise SystemExit("No populated .studyThumb elements found.")

    print(study_thumbs[0])

    data = []
    for study_thumb in study_thumbs:
        # Get the Image id from idr from the viewer_link object
        # e.g. <a class="viewer_link" href="/webclient/img_detail/15199994/" target="_blank">
        image_id = study_thumb.select_one(".viewer_link").get("href", "").split("/")[-2]

        thumbnail_url = (
            f"https://idr.openmicroscopy.org/webgateway/render_thumbnail/{image_id}/"
        )

        project_id = study_thumb.get("data-idrid")

        print(image_id, project_id, thumbnail_url)
        data.append((image_id, project_id, thumbnail_url))

    # Save the data to a TSV file
    with open("idr_study_thumbnails.tsv", "w") as f:
        f.write("image_id\tproject_id\tthumbnail_url\n")
        for image_id, project_id, thumbnail_url in data:
            f.write(f"{image_id}\t{project_id}\t{thumbnail_url}\n")


if __name__ == "__main__":
    main()
