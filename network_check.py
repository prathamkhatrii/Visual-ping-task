"""
network_check.py

Isolates whether your machine has a DNS problem (which won't matter for the
challenge, since 54.214.7.161 is a raw IP) or a broader network/firewall
problem (which would matter).

Usage:
    python network_check.py
"""

import socket
import subprocess
import sys

TARGET_IP = "54.214.7.161"


def check_dns():
    print("[*] Testing DNS resolution (example.com)...")
    try:
        socket.gethostbyname("example.com")
        print("[OK] DNS resolution works.")
        return True
    except socket.gaierror as e:
        print(f"[!] DNS resolution FAILED: {e}")
        print("    This matches the ERR_NAME_NOT_RESOLVED error you saw.")
        return False


def check_raw_tcp():
    print(f"\n[*] Testing raw TCP connection to {TARGET_IP}:80 (no DNS needed)...")
    try:
        with socket.create_connection((TARGET_IP, 80), timeout=8) as s:
            print(f"[OK] TCP connection to {TARGET_IP}:80 succeeded.")
            return True
    except Exception as e:
        print(f"[!] TCP connection FAILED: {e}")
        print("    This means the network itself (not just DNS) is blocking "
              "you from reaching the challenge server.")
        return False


async def check_playwright_ip():
    from playwright.async_api import async_playwright

    print(f"\n[*] Testing Playwright/Chromium navigation directly to http://{TARGET_IP}/ ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            resp = await page.goto(f"http://{TARGET_IP}/", timeout=15000)
            print(f"[OK] Loaded challenge site. HTTP status: {resp.status if resp else 'unknown'}")
            title = await page.title()
            print(f"     Page title: '{title}'")
            return True
        except Exception as e:
            print(f"[!] Playwright navigation to challenge site FAILED: {e}")
            return False
        finally:
            await browser.close()


def main():
    print("=" * 60)
    print("Network diagnostic")
    print("=" * 60)

    dns_ok = check_dns()
    tcp_ok = check_raw_tcp()

    import asyncio
    pw_ok = asyncio.run(check_playwright_ip())

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"DNS resolution:              {'OK' if dns_ok else 'FAILING'}")
    print(f"Raw TCP to challenge IP:     {'OK' if tcp_ok else 'FAILING'}")
    print(f"Playwright to challenge IP:  {'OK' if pw_ok else 'FAILING'}")

    if pw_ok:
        print("\n[*] Good news: task.py should work fine even though the DNS "
              "smoke test failed -- the challenge target is a raw IP and "
              "doesn't need DNS. Go ahead and run task.py directly.")
    elif tcp_ok and not pw_ok:
        print("\n[*] TCP reaches the server but Playwright/Chromium can't load "
              "it. Re-run with headless=False locally to watch what happens, "
              "or check for a proxy environment variable (HTTP_PROXY/HTTPS_PROXY) "
              "that might be interfering.")
    elif not tcp_ok:
        print("\n[*] Your machine can't reach 54.214.7.161 at all. This is "
              "likely a VPN, corporate firewall, or captive portal blocking "
              "outbound connections. Try: disabling VPN, checking if you're "
              "on a restricted network (e.g. corporate Wi-Fi), or running "
              "this from a different network to confirm.")
        if not dns_ok:
            print("    DNS is also failing, which points toward a broader "
                  "network/proxy misconfiguration rather than a DNS-specific issue.")


if __name__ == "__main__":
    main()
