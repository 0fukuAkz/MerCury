import pytest

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Page = None  # type: ignore
    expect = None  # type: ignore

pytestmark = pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed")

def test_login_flow(page: Page, base_url):
    """Test successful login and redirect to dashboard."""
    page.goto(f"{base_url}/login")
    
    # Check title
    expect(page).to_have_title("Login - MerCury")
    
    # Fill login form
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "password")
    
    # Click login
    page.click("button[type='submit']")
    
    # Should redirect to dashboard
    expect(page).to_have_url(f"{base_url}/")
    expect(page.locator("h1")).to_contain_text("Dashboard")

def test_login_failure(page: Page, base_url):
    """Test invalid login attempts."""
    page.goto(f"{base_url}/login")
    
    page.fill("input[name='username']", "wrong")
    page.fill("input[name='password']", "wrong")
    
    page.click("button[type='submit']")
    
    # Should show error message
    expect(page.locator(".flash")).to_be_visible()
    expect(page.locator(".flash")).to_contain_text("Invalid username or password")

def test_campaign_page_access(page: Page, base_url):
    """Test accessing campaigns page after login."""
    # Login first
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "password")
    page.click("button[type='submit']")
    
    # Wait for dashboard
    expect(page).to_have_url(f"{base_url}/")
    
    # Navigate to campaigns
    page.click("a[href='/campaigns']")
    
    # Check header
    expect(page.locator("h1")).to_contain_text("Campaigns")
    # Check for 'New Campaign' button
    expect(page.locator("a.btn-primary")).to_contain_text("New Campaign")
