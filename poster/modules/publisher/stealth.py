"""
Playwright stealth utilities — applies anti-detection patches to browser contexts.
"""
from playwright.async_api import BrowserContext
from playwright_stealth import Stealth

STEALTH_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-gpu-sandbox',
]

DEFAULT_VIEWPORT = {'width': 1280, 'height': 720}


async def apply_stealth(context: BrowserContext) -> None:
    """Apply stealth patches to a browser context.

    Runs playwright-stealth's async helper and masks automation indicators
    so automation signals are hidden from JavaScript fingerprinting scripts.
    """
    try:
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
    except Exception:
        pass

    # Ensure navigator.webdriver is undefined and chrome runtime exists
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        if (!window.chrome) {
            window.chrome = {runtime: {}};
        }
        const originalQuery = window.navigator.permissions ? window.navigator.permissions.query : null;
        if (originalQuery) {
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : originalQuery(parameters)
            );
        }
    """)


def get_launch_options(headless: bool = False) -> dict:
    """Return browser launch keyword arguments suitable for Playwright.

    Args:
        headless: Whether to launch the browser in headless mode.
                  Defaults to False — many platforms detect headless mode.

    Returns:
        A dict suitable for unpacking into ``playwright.chromium.launch(**opts)``
        or ``playwright.chromium.launch_persistent_context(..., **opts)``.
    """
    import shutil
    import sys

    opts = {
        'headless': headless,
        'args': STEALTH_ARGS,
        'ignore_default_args': ['--enable-automation'],
        'slow_mo': 0,
    }
    if sys.platform == 'win32':
        opts['channel'] = 'chrome'
    elif shutil.which('google-chrome') or shutil.which('google-chrome-stable'):
        opts['channel'] = 'chrome'

    return opts


def get_context_options(
    locale: str = 'id-ID',
    timezone: str = 'Asia/Jakarta',
    user_agent: str | None = None,
) -> dict:
    """Return browser-context keyword arguments.

    These options are passed to ``browser.new_context(**opts)`` or
    included in ``launch_persistent_context(..., **opts)``.

    Args:
        locale: Browser locale string, e.g. ``'id-ID'``.
        timezone: IANA timezone identifier, e.g. ``'Asia/Jakarta'``.
        user_agent: Custom User-Agent. If None, uses Chrome's native matching UA.

    Returns:
        Dict of context options.
    """
    opts = {
        'viewport': DEFAULT_VIEWPORT,
        'locale': locale,
        'timezone_id': timezone,
        'color_scheme': 'light',
        'device_scale_factor': 1,
        'is_mobile': False,
        'has_touch': False,
        'java_script_enabled': True,
        'bypass_csp': False,
        'extra_http_headers': {
            'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
        },
    }
    if user_agent:
        opts['user_agent'] = user_agent
    return opts
