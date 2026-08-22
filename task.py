import asyncio
import base64
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Configuration & Output Setup
# ---------------------------------------------------------------------------
START_URL = "http://54.214.7.161/"
AUTH_USER = "pratham.khatri"
AUTH_PASS = "5c9202a50c0748d736be"

OUTPUT_DIR = Path(r"C:\Users\Pratham\Python_Task")
OUTPUT_FILE = OUTPUT_DIR / "passwords.txt"
DOWNLOAD_DIR = OUTPUT_DIR / "_downloads"

PASSWORD_REGEX_TEXT = re.compile(r"VISUALPING\{[0-9a-fA-F]{16}\}")
PASSWORD_REGEX_BYTES = re.compile(rb"VISUALPING\{[0-9a-fA-F]{16}\}")

DEMO_PASSWORD = "VISUALPING{0000deadbeef0000}"

BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
HEX_CANDIDATE_RE = re.compile(r"(?:[0-9a-fA-F]{2}){20,}")

TARGET_COUNT = 8

found_passwords = set()
visited_urls = set()
urls_to_visit = set([START_URL])

# Try to import pypdf for real PDF text extraction. Optional -- if it's not
# installed, PDFs still get scanned as raw bytes (which catches metadata
# fields like /Keywords, /Subject, /Author, but NOT compressed page text).
try:
    from pypdf import PdfReader
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False
    print("[!] pypdf not installed -- PDF page text won't be extracted.")
    print("    Run: pip install pypdf")


def save_passwords():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for pwd in sorted(found_passwords):
            f.write(f"{pwd}\n")


def _record(match: str, source_label: str):
    if match == DEMO_PASSWORD:
        return
    if match not in found_passwords:
        found_passwords.add(match)
        print(f"\n\U0001F389 [PASSWORD #{len(found_passwords)} FOUND] {match}")
        print(f"   \u2514\u2500\u2500 Source: {source_label}\n")
        save_passwords()


def extract_passwords(text: str, source_label: str):
    if not text:
        return

    for m in PASSWORD_REGEX_TEXT.findall(text):
        _record(m, source_label)

    for m in PASSWORD_REGEX_TEXT.findall(unquote(text)):
        _record(m, f"{source_label} [url-decoded]")

    for m in PASSWORD_REGEX_TEXT.findall(text[::-1]):
        _record(m, f"{source_label} [reversed]")

    for candidate in set(BASE64_CANDIDATE_RE.findall(text)):
        for padded in (candidate, candidate + "=", candidate + "=="):
            try:
                decoded = base64.b64decode(padded, validate=False).decode(
                    "utf-8", errors="ignore"
                )
            except Exception:
                continue
            for m in PASSWORD_REGEX_TEXT.findall(decoded):
                _record(m, f"{source_label} [base64-decoded]")
            break

    for candidate in set(HEX_CANDIDATE_RE.findall(text)):
        try:
            decoded = bytes.fromhex(candidate).decode("utf-8", errors="ignore")
        except Exception:
            continue
        for m in PASSWORD_REGEX_TEXT.findall(decoded):
            _record(m, f"{source_label} [hex-decoded]")


def extract_pdf_text(data: bytes, source_label: str):
    """Real PDF text extraction -- raw byte regex misses this because PDF
    page content streams are almost always zlib-compressed."""
    if not HAVE_PYPDF:
        return
    try:
        import io
        reader = PdfReader(io.BytesIO(data))
        # Page text
        full_text = []
        for page in reader.pages:
            try:
                full_text.append(page.extract_text() or "")
            except Exception:
                pass
        extract_passwords("\n".join(full_text), f"{source_label} [PDF text]")

        # Document metadata (Author, Subject, Keywords, custom fields, etc.)
        if reader.metadata:
            extract_passwords(str(reader.metadata), f"{source_label} [PDF metadata]")

        # Annotations (comments, links) sometimes carry hidden text too
        for page in reader.pages:
            try:
                if "/Annots" in page:
                    extract_passwords(str(page["/Annots"]), f"{source_label} [PDF annotations]")
            except Exception:
                pass
    except Exception as e:
        print(f"[!] PDF parse failed for {source_label}: {e}")


def extract_passwords_bytes(data: bytes, source_label: str, content_type: str = ""):
    if not data:
        return
    for m in PASSWORD_REGEX_BYTES.findall(data):
        _record(m.decode("utf-8", errors="ignore"), source_label)

    if b"VklTVUF" in data:
        try:
            decoded = base64.b64decode(data).decode("utf-8", errors="ignore")
            extract_passwords(decoded, f"{source_label} [base64 whole-body]")
        except Exception:
            pass

    try:
        text = data.decode("utf-8", errors="ignore")
        extract_passwords(text, source_label)
    except Exception:
        pass

    if "pdf" in content_type.lower() or data[:4] == b"%PDF":
        extract_pdf_text(data, source_label)


def is_crawler_trap(url: str) -> bool:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    if "page" in query_params:
        try:
            if int(query_params["page"][0]) > 3:
                return True
        except ValueError:
            pass
    return False


async def handle_response(response):
    try:
        extract_passwords(str(response.headers), f"Headers [{response.status}] ({response.url})")
        try:
            req_headers = await response.request.all_headers()
            extract_passwords(str(req_headers), f"Request Headers ({response.url})")
        except Exception:
            pass

        content_type = response.headers.get("content-type", "")
        try:
            body_bytes = await response.body()
        except Exception:
            # This is exactly what happens for real file downloads -- the
            # body was streamed to the download manager instead of being
            # buffered for script access. The context.on("download")
            # handler below is what actually catches those.
            return
        extract_passwords_bytes(body_bytes, f"Body ({response.url})", content_type)
    except Exception:
        pass


async def handle_download(download):
    """Catches file downloads (PDFs, attachments, etc.) that response.body()
    can't read because Chromium streams them straight to disk."""
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        suggested = download.suggested_filename or "download.bin"
        safe_name = re.sub(r"[^\w.\-]", "_", suggested)
        save_path = DOWNLOAD_DIR / safe_name
        await download.save_as(str(save_path))
        print(f"[*] Downloaded file: {download.url} -> {save_path}")

        data = save_path.read_bytes()
        extract_passwords_bytes(data, f"Download ({download.url})")
    except Exception as e:
        print(f"[!] Failed to process download {download.url}: {e}")


async def handle_new_page(new_page, main_page_ref):
    """Catches links that open in a new tab/window via target=_blank or
    window.open() -- these are never HTML <a> navigations the crawl loop
    would otherwise see."""
    if new_page is main_page_ref[0]:
        # context.on("page", ...) also fires for our own main page at
        # creation time -- never touch/close that one.
        return
    try:
        await new_page.wait_for_load_state("load", timeout=8000)
    except Exception:
        pass
    try:
        url = new_page.url
        if url and url.startswith("http") and url not in visited_urls:
            if urlparse(url).netloc == urlparse(START_URL).netloc:
                urls_to_visit.add(url)
                print(f"[*] Discovered via new tab/popup: {url}")
        # Also grab whatever's already rendered before we close it.
        try:
            content = await new_page.content()
            extract_passwords(content, f"Popup Content ({url})")
        except Exception:
            pass
    finally:
        try:
            await new_page.close()
        except Exception:
            pass


SHADOW_WALK_JS = """
() => {
    function walk(node) {
        let out = node.outerHTML || '';
        if (node.shadowRoot) {
            out += ' [SHADOW] ' + node.shadowRoot.innerHTML;
            node.shadowRoot.querySelectorAll('*').forEach(child => {
                if (child.shadowRoot) out += walk(child);
            });
        }
        return out;
    }
    let all = '';
    document.querySelectorAll('*').forEach(el => {
        if (el.shadowRoot) all += walk(el);
    });
    return all;
}
"""

# Injected into every page/frame in the context BEFORE any page script runs.
# Captures Server-Sent Events (EventSource) and any fetch() response whose
# content-type looks like a stream, since these deliver data asynchronously
# after the initial page load and response.body() won't see it.
STREAM_CAPTURE_INIT_JS = """
window.__captured_messages = [];
(function() {
    const OrigES = window.EventSource;
    if (OrigES) {
        function PatchedES(url, opts) {
            const es = new OrigES(url, opts);
            es.addEventListener('message', function(e) {
                window.__captured_messages.push('SSE ' + url + ': ' + e.data);
            });
            es.addEventListener('error', function() {});
            return es;
        }
        PatchedES.prototype = OrigES.prototype;
        window.EventSource = PatchedES;
    }

    const origFetch = window.fetch;
    if (origFetch) {
        window.fetch = async function(...args) {
            const res = await origFetch(...args);
            try {
                const ct = res.headers.get('content-type') || '';
                if (ct.includes('event-stream') || ct.includes('stream') || ct.includes('json')) {
                    const clone = res.clone();
                    clone.text().then(t => {
                        window.__captured_messages.push('FETCH ' + args[0] + ': ' + t);
                    }).catch(() => {});
                }
            } catch (e) {}
            return res;
        };
    }
})();
"""


async def crawl():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            http_credentials={"username": AUTH_USER, "password": AUTH_PASS},
            ignore_https_errors=True,
            accept_downloads=True,
        )
        await context.add_init_script(STREAM_CAPTURE_INIT_JS)

        # Create the main page FIRST, before attaching the popup listener --
        # context.on("page", ...) fires for this page too, and we must not
        # let the popup handler close our own crawling page.
        page = await context.new_page()
        main_page_ref = [page]

        context.on("download", lambda d: asyncio.create_task(handle_download(d)))
        context.on("page", lambda p_: asyncio.create_task(handle_new_page(p_, main_page_ref)))

        page.on("response", handle_response)
        page.on("dialog", lambda d: extract_passwords(d.message, f"Alert Popup ('{d.message}')"))
        page.on("console", lambda m: extract_passwords(m.text, f"Console ({m.type})"))
        page.on(
            "websocket",
            lambda ws: ws.on(
                "framereceived", lambda payload: extract_passwords(str(payload), "WebSocket Frame")
            ),
        )

        hidden_paths = [
            "/404-test-page-xyz",
            "/favicon.ico",
            "/robots.txt",
            "/sitemap.xml",
            "/manifest.json",
            "/.env",
            "/config.js",
            "/humans.txt",
            "/security.txt",
            "/.well-known/security.txt",
        ]
        for path in hidden_paths:
            urls_to_visit.add(urljoin(START_URL, path))

        real_password_count = lambda: len(found_passwords - {DEMO_PASSWORD})

        while urls_to_visit and real_password_count() < TARGET_COUNT:
            current_url = urls_to_visit.pop()

            if current_url in visited_urls or urlparse(current_url).netloc != urlparse(START_URL).netloc:
                continue
            if is_crawler_trap(current_url):
                continue

            print(f"[*] Navigating: {current_url}")
            visited_urls.add(current_url)

            try:
                try:
                    await page.goto(current_url, wait_until="networkidle", timeout=15000)
                except Exception as nav_err:
                    # A direct navigation to a downloadable file often raises
                    # here even though the download itself succeeds via the
                    # context "download" handler above -- don't bail out.
                    print(f"    (goto raised: {nav_err} -- continuing, download handler may still fire)")

                # Give streaming connections (SSE/WebSocket/live fetch polling)
                # time to actually deliver data. Longer on pages that sound
                # like live/real-time endpoints.
                extra_wait = 4000 if any(k in current_url for k in ("report", "status", "live")) else 1200
                await page.wait_for_timeout(extra_wait)

                cookies = await context.cookies()
                extract_passwords(str(cookies), f"Cookies ({current_url})")

                storage = await page.evaluate(
                    """() => ({
                        local: JSON.stringify(localStorage),
                        session: JSON.stringify(sessionStorage)
                    })"""
                )
                extract_passwords(storage.get("local"), f"LocalStorage ({current_url})")
                extract_passwords(storage.get("session"), f"SessionStorage ({current_url})")

                full_html = await page.content()
                extract_passwords(full_html, f"Full Page Source ({current_url})")

                shadow_html = await page.evaluate(SHADOW_WALK_JS)
                extract_passwords(shadow_html, f"Shadow DOM ({current_url})")

                for media in (None, "print"):
                    if media:
                        await page.emulate_media(media=media)
                    css_pseudo = await page.evaluate(
                        """() => Array.from(document.querySelectorAll('*')).map(el =>
                            window.getComputedStyle(el, '::before').getPropertyValue('content') +
                            window.getComputedStyle(el, '::after').getPropertyValue('content')
                        ).join(' ')"""
                    )
                    extract_passwords(css_pseudo, f"CSS Pseudo [{media or 'screen'}] ({current_url})")
                await page.emulate_media(media=None)

                idb_data = await page.evaluate(
                    """async () => {
                        if (!window.indexedDB || !indexedDB.databases) return '';
                        try {
                            const dbs = await indexedDB.databases();
                            const results = [];
                            for (const dbInfo of dbs) {
                                await new Promise((resolve) => {
                                    const req = indexedDB.open(dbInfo.name);
                                    req.onsuccess = () => {
                                        const db = req.result;
                                        const storeNames = Array.from(db.objectStoreNames);
                                        if (storeNames.length === 0) { resolve(); return; }
                                        const tx = db.transaction(storeNames, 'readonly');
                                        let remaining = storeNames.length;
                                        storeNames.forEach(name => {
                                            const store = tx.objectStore(name);
                                            const getAll = store.getAll();
                                            getAll.onsuccess = () => {
                                                results.push(JSON.stringify(getAll.result));
                                                remaining--;
                                                if (remaining === 0) resolve();
                                            };
                                            getAll.onerror = () => { remaining--; if (remaining === 0) resolve(); };
                                        });
                                    };
                                    req.onerror = () => resolve();
                                });
                            }
                            return results.join(' ');
                        } catch (e) { return ''; }
                    }"""
                )
                extract_passwords(idb_data, f"IndexedDB contents ({current_url})")

                cache_data = await page.evaluate(
                    """async () => {
                        if (!('caches' in window)) return '';
                        try {
                            const names = await caches.keys();
                            const bodies = [];
                            for (const name of names) {
                                const cache = await caches.open(name);
                                const requests = await cache.keys();
                                for (const req of requests) {
                                    bodies.push(req.url);
                                    try {
                                        const res = await cache.match(req);
                                        bodies.push(await res.text());
                                    } catch (e) {}
                                }
                            }
                            return bodies.join(' ');
                        } catch (e) { return ''; }
                    }"""
                )
                extract_passwords(cache_data, f"CacheStorage contents ({current_url})")

                js_dump = await page.evaluate(
                    """() => {
                        const cache = new Set();
                        return JSON.stringify(window, (key, val) => {
                            if (typeof val === 'object' && val !== null) {
                                if (cache.has(val)) return;
                                cache.add(val);
                            }
                            return val;
                        });
                    }"""
                )
                extract_passwords(js_dump, f"Global JS Memory ({current_url})")

                for frame in page.frames:
                    try:
                        f_content = await frame.content()
                        extract_passwords(f_content, f"Iframe Content ({frame.url})")
                    except Exception:
                        pass

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(300)

                hover_targets = await page.query_selector_all("div, span, img, tr, td")
                for el in hover_targets[:15]:
                    try:
                        await el.hover(timeout=200)
                    except Exception:
                        pass

                if "page=" not in current_url:
                    clickables = await page.query_selector_all(
                        "button, [role='button'], input[type='submit'], summary, [onclick]"
                    )
                    for btn in clickables:
                        try:
                            if await btn.is_visible():
                                await btn.click(timeout=800)
                                await page.wait_for_timeout(200)
                        except Exception:
                            pass

                # Give any download / new-tab / streaming events triggered by
                # those clicks a moment to actually fire and be handled.
                await page.wait_for_timeout(1500)

                full_html_after = await page.content()
                extract_passwords(full_html_after, f"Full Page Source Post-Interaction ({current_url})")

                # Pull whatever the SSE/fetch-stream capture script collected.
                stream_messages = await page.evaluate(
                    "() => { const m = window.__captured_messages || []; window.__captured_messages = []; return m.join(' ||| '); }"
                )
                extract_passwords(stream_messages, f"SSE/Stream capture ({current_url})")

                js_scripts = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('script[src]')).map(s => s.src)"
                )
                for script_url in js_scripts:
                    map_url = script_url + ".map"
                    if map_url not in visited_urls:
                        urls_to_visit.add(map_url)

                dom_links = await page.evaluate(
                    """() => {
                        const found = new Set();
                        document.querySelectorAll(
                            '[href], [src], form[action], [data-href], [data-src]'
                        ).forEach(e => {
                            ['href', 'src', 'action', 'data-href', 'data-src'].forEach(attr => {
                                const v = e.getAttribute && e.getAttribute(attr);
                                if (v) found.add(v);
                            });
                        });
                        return Array.from(found);
                    }"""
                )
                for link in dom_links:
                    abs_url = urljoin(current_url, link)
                    if urlparse(abs_url).netloc == urlparse(START_URL).netloc and abs_url not in visited_urls:
                        if not is_crawler_trap(abs_url):
                            urls_to_visit.add(abs_url)

            except Exception as e:
                print(f"    (unexpected error on {current_url}: {e})")

        # Let any final in-flight downloads/popups/streams settle.
        await page.wait_for_timeout(2000)
        await browser.close()

    save_passwords()
    print("\n" + "=" * 50)
    print(f"CRAWL COMPLETE: Found {real_password_count()}/{TARGET_COUNT} real passwords")
    print(f"Saved results to: {OUTPUT_FILE}")
    print("=" * 50)
    for pwd in sorted(found_passwords - {DEMO_PASSWORD}):
        print(f"  -> {pwd}")


if __name__ == "__main__":
    asyncio.run(crawl())