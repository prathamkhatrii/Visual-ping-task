Hi,

Please find attached the three files for the crawler challenge:

setup_check.py — verifies/installs the required environment (Playwright + Chromium)
network_check.py — optional diagnostic to confirm connectivity to the challenge site
task.py — the crawler itself

To run:

Run python setup_check.py first to set up the environment — it installs the Playwright package and the Chromium browser binary if they're missing, then does a quick launch test to confirm everything works.
Once that passes, run python task.py to execute the crawl.

The script authenticates via HTTP Basic Auth as instructed, crawls the site starting from the homepage, and inspects each page well beyond just visible HTML — headers, cookies, storage, JS/CSS source, downloads, and more. Found passwords are printed to the console as they're discovered and saved to passwords.txt.

Thanks,
Pratham
