"""End-to-end Playwright tests for Talk2Excel.

Each test launches the Streamlit app, uploads the sample data file,
sends a natural-language query through the real LLM, and validates
the result against the acceptance criteria.
"""

import os
import re
import subprocess
import time
import urllib.request

import pytest
from playwright.sync_api import Page, expect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_URL = "http://localhost:8501"
DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "sample_superstore.xls"
)
TIMEOUT = 30_000  # 30 s default per Playwright action


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _streamlit_server():
    """Start Streamlit once for the whole test session, then tear it down."""
    env = os.environ.copy()
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    proc = subprocess.Popen(
        [
            "streamlit", "run", "app.py",
            "--server.port", "8501",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    # Wait for the server to be ready
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(APP_URL, timeout=2)
            break
        except Exception:
            continue
    else:
        proc.terminate()
        raise RuntimeError("Streamlit server did not start in time")
    yield
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def app_page(page: Page):
    """Navigate to the running app and return the page."""
    page.set_default_timeout(TIMEOUT)
    page.goto(APP_URL, wait_until="networkidle")
    # Wait for Streamlit to fully render
    page.wait_for_selector('[data-testid="stApp"]', timeout=TIMEOUT)
    return page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _upload_file(page: Page) -> None:
    """Upload the sample Excel file and wait for schema to appear."""
    # Wait for Streamlit file uploader to be fully rendered
    page.wait_for_selector(
        '[data-testid="stFileUploader"]', timeout=TIMEOUT
    )
    page.wait_for_timeout(1000)
    file_input = page.query_selector('input[type="file"]')
    assert file_input is not None, "File input not found on page"
    file_input.set_input_files(DATA_FILE)
    # Wait for the schema section to appear (proof that upload worked)
    page.wait_for_selector("text=Data Schema", timeout=TIMEOUT)
    # Give Streamlit a moment to finish processing
    page.wait_for_timeout(2000)


def _send_chat_message(page: Page, message: str) -> None:
    """Type a message in the chat input and press Enter."""
    chat_input = page.locator('textarea[data-testid="stChatInputTextArea"]')
    chat_input.fill(message)
    chat_input.press("Enter")


def _wait_for_response(page: Page, timeout: int = 60_000) -> str:
    """Wait for the assistant response to finish and return its text."""
    # First wait a moment for the spinner to appear
    page.wait_for_timeout(2000)
    # Then wait for spinner to disappear (means processing is done)
    page.wait_for_function(
        """() => {
            const spinners = document.querySelectorAll('[data-testid="stSpinner"]');
            return spinners.length === 0;
        }""",
        timeout=timeout,
    )
    page.wait_for_timeout(1000)
    # Get the last assistant message content
    messages = page.locator('[data-testid="stChatMessage"]')
    count = messages.count()
    if count == 0:
        return ""
    last = messages.nth(count - 1)
    return last.inner_text()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExcelUploadAndSchema:
    """Acceptance criterion 2: Excel upload + schema display."""

    def test_upload_and_schema(self, app_page: Page):
        _upload_file(app_page)
        schema_area = app_page.locator("text=Data Schema")
        expect(schema_area).to_be_visible()
        # Verify key columns from the superstore dataset
        page_text = app_page.content()
        assert "Sales" in page_text
        assert "Profit" in page_text
        assert "Region" in page_text
        assert "Category" in page_text


class TestOrdersCount:
    """Acceptance criterion 3: 'Show the number of all orders' -> 10194."""

    def test_orders_count(self, app_page: Page):
        _upload_file(app_page)
        _send_chat_message(app_page, "Show the number of all orders")
        response_text = _wait_for_response(app_page, timeout=60_000)
        # The number 10194 (or 10,194) must appear in the response
        normalized = response_text.replace(",", "")
        assert "10194" in normalized, (
            f"Expected 10194 in response: {response_text}"
        )


class TestTopCustomers:
    """Acceptance criterion 4: top 10 customers by total sales."""

    def test_top_customers(self, app_page: Page):
        _upload_file(app_page)
        _send_chat_message(
            app_page, "List the top 10 customers by total sales"
        )
        response_text = _wait_for_response(app_page, timeout=60_000)
        assert "Sean Miller" in response_text, (
            f"Expected 'Sean Miller' in response: {response_text}"
        )


class TestWestRegionProfit:
    """Acceptance criterion 5: total profit in the West region ~ 110,799."""

    def test_west_profit(self, app_page: Page):
        _upload_file(app_page)
        _send_chat_message(
            app_page, "Show total profit in the West region"
        )
        response_text = _wait_for_response(app_page, timeout=60_000)
        normalized = response_text.replace(",", "").replace("$", "")
        # Accept 110799 or 110798 (rounding differences)
        has_profit = (
            "110799" in normalized
            or "110798" in normalized
            or re.search(r"110[\s.,]*79[89]", normalized)
        )
        assert has_profit, (
            "Expected ~110,799 in response: {}".format(response_text)
        )


class TestSalesBySubCategory:
    """Acceptance criterion 6: Technology sub-category sales table + chart."""

    def test_subcategory_sales(self, app_page: Page):
        _upload_file(app_page)
        _send_chat_message(
            app_page,
            "Show total sales by sub-category in the Technology category"
            " as a table and chart",
        )
        response_text = _wait_for_response(app_page, timeout=90_000)
        # Check that key sub-categories appear
        assert "Phones" in response_text, (
            f"Expected 'Phones' in response: {response_text}"
        )
        assert "Machines" in response_text, (
            f"Expected 'Machines' in response: {response_text}"
        )
        # Check a chart image is present (base64 img tag)
        page_html = app_page.content()
        assert "<img" in page_html.lower(), (
            "Expected a chart image in the response"
        )


class TestHighestProfitProduct:
    """Acceptance criterion 7: highest profit product."""

    def test_highest_profit_product(self, app_page: Page):
        _upload_file(app_page)
        _send_chat_message(
            app_page,
            "Which product generated the highest total profit?",
        )
        response_text = _wait_for_response(app_page, timeout=60_000)
        assert "Canon" in response_text and "2200" in response_text, (
            f"Expected 'Canon imageCLASS 2200' in response: {response_text}"
        )
