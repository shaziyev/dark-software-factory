from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP_URL = "http://127.0.0.1:8501"
SAMPLE_FILE = ROOT / "data" / "sample_superstore.xls"


def wait_for_server(url: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except urllib.error.URLError:
            time.sleep(1)

    raise RuntimeError(
        f"Streamlit server at {url} did not become ready within {timeout_seconds} seconds."
    )


def ask_question(page, question: str) -> None:
    page.get_by_label("Ask a question about your spreadsheet").fill(question)
    page.get_by_role("button", name="Ask").click()


def assert_answer_contains(page, expected_text: str, timeout_ms: int = 90000) -> None:
    expect(page.locator("[data-testid='assistant-answer']").last).to_contain_text(
        expected_text,
        timeout=timeout_ms,
    )


def assert_artifact_summary(page, expected_text: str, timeout_ms: int = 90000) -> None:
    expect(page.locator("[data-testid='artifact-summary']").last).to_contain_text(
        expected_text,
        timeout=timeout_ms,
    )


def open_ready_page(browser, verify_connection: bool = False):
    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    page.set_default_timeout(30000)
    page.goto(APP_URL, wait_until="domcontentloaded")

    expect(page.get_by_role("button", name="Test OpenAI connection")).to_be_visible(timeout=30000)

    if verify_connection:
        page.get_by_role("button", name="Test OpenAI connection").click()
        expect(page.get_by_text("Connected to OpenAI.")).to_be_visible(timeout=30000)

    page.locator("input[type='file']").set_input_files(str(SAMPLE_FILE))
    expect(page.get_by_text("Schema ready for sample_superstore.xls")).to_be_visible(timeout=30000)
    expect(page.get_by_label("Ask a question about your spreadsheet")).to_be_enabled(timeout=30000)
    return page


def run() -> None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the Playwright run.")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.headless",
            "true",
            "--server.port",
            "8501",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        wait_for_server(APP_URL)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = open_ready_page(browser, verify_connection=True)

            ask_question(page, "Show the number of all orders")
            assert_answer_contains(page, "10,194")
            browser.close()

            browser = playwright.chromium.launch()
            page = open_ready_page(browser)
            ask_question(page, "List the top 10 customers by total sales")
            expect(page.get_by_text("Sean Miller")).to_be_visible(timeout=90000)
            assert_artifact_summary(page, "first_table_rows:10")
            browser.close()

            browser = playwright.chromium.launch()
            page = open_ready_page(browser)
            ask_question(page, "Show total profit in the West region")
            expect(page.locator("[data-testid='assistant-answer']").last).to_contain_text(
                "110,799",
                timeout=90000,
            )
            browser.close()

            browser = playwright.chromium.launch()
            page = open_ready_page(browser)
            ask_question(
                page,
                "Show total sales by sub-category in the Technology category as a table and chart",
            )
            assert_artifact_summary(page, "tables:1 | charts:1 | first_table_rows:4")
            result_table = page.get_by_test_id("stTableStyledTable").last
            expect(result_table).to_contain_text("Phones", timeout=90000)
            expect(result_table).to_contain_text("331,843", timeout=90000)
            expect(result_table).to_contain_text("Machines", timeout=90000)
            expect(result_table).to_contain_text("189,925", timeout=90000)
            expect(result_table).to_contain_text("Accessories", timeout=90000)
            expect(result_table).to_contain_text("167,380", timeout=90000)
            expect(result_table).to_contain_text("Copiers", timeout=90000)
            expect(result_table).to_contain_text("150,745", timeout=90000)
            expect(page.locator("img").last).to_be_visible(timeout=30000)
            browser.close()

            browser = playwright.chromium.launch()
            page = open_ready_page(browser)
            ask_question(page, "Which product generated the highest total profit?")
            assert_answer_contains(page, "Canon imageCLASS 2200 Advanced Copier")
            assert_answer_contains(page, "25,200")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    run()
