"""The daily refresh run draws the share cards with Chromium from Playwright on GitHub's runner.

GitHub moves `ubuntu-latest` to Ubuntu 26.04 by 19 Nov 2026
(github.com/actions/runner-images/issues/14748). Playwright supports Ubuntu 26.04 from
version 1.61 ("Playwright now supports Ubuntu 26.04", playwright.dev release notes); on 1.60
`playwright install --with-deps chromium` refuses that image, and that step is not
non-fatal, so the run would stop before the day's data is committed (aios-harness#149).
"""
from importlib.metadata import version

UBUNTU_26_04_FIRST_PLAYWRIGHT = (1, 61)


def test_pinned_playwright_supports_ubuntu_26_04():
    major, minor = (int(p) for p in version("playwright").split(".")[:2])
    assert (major, minor) >= UBUNTU_26_04_FIRST_PLAYWRIGHT
