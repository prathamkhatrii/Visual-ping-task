"""
setup_check.py

Run this once before task.py to make sure your environment is ready:
  1. Installs the playwright Python package if missing.
  2. Installs the Chromium browser binary Playwright needs (this is a
     separate download from the pip package, and is the #1 reason
     "playwright._impl._api_types.Error: Executable doesn't exist" shows up).
  3. Launches Chromium headless and hits a test page to confirm everything
     actually works end-to-end.

Usage:
    python setup_check.py
"""

import subprocess
import sys


def run(cmd, description):
    print(f"\n[*] {description}")
    print(f"    $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"[!] FAILED (exit code {result.returncode})")
        if result.stderr.strip():
            print(result.stderr.strip())
        return False
    print("[OK]")
    return True


def ensure_playwright_installed():
    try:
        import playwright  # noqa: F401
        print("[OK] playwright package already installed")
        return True
    except ImportError:
        return run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            "Installing playwright package",
        )


def ensure_chromium_installed():
    return run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        "Installing Chromium browser binary for Playwright",
    )


def ensure_system_deps():
    # On fresh Linux machines Chromium also needs OS-level shared libraries.
    # This step is safe to skip on Windows/macOS or if it fails for
    # permission reasons (sudo) -- it's a nice-to-have, not a hard blocker.
    run(
        [sys.executable, "-m", "playwright", "install-deps", "chromium"],
        "Installing OS-level dependencies for Chromium (may require sudo; "
        "safe to ignore failures on Windows/macOS)",
    )


async def smoke_test():
    from playwright.async_api import async_playwright

    print("\n[*] Launching headless Chromium and loading a test page...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://example.com", timeout=15000)
        title = await page.title()
        await browser.close()
        print(f"[OK] Page loaded successfully. Title: '{title}'")


def main():
    print("=" * 60)
    print("Playwright environment check")
    print("=" * 60)

    if not ensure_playwright_installed():
        print("\n[!] Could not install the playwright package. Fix this "
              "before running task.py.")
        sys.exit(1)

    if not ensure_chromium_installed():
        print("\n[!] Could not install the Chromium binary. Fix this "
              "before running task.py.")
        sys.exit(1)

    ensure_system_deps()

    import asyncio
    try:
        asyncio.run(smoke_test())
    except Exception as e:
        print(f"\n[!] Smoke test failed: {e}")
        print("    Chromium is installed but failed to launch/navigate. "
              "Check the error above -- common causes are missing OS "
              "libraries (try running this script with sudo on Linux) or "
              "a blocked network connection.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("All checks passed -- you're ready to run task.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
