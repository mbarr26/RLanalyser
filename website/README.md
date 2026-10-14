# RL Analyser website

A static marketing and download site in the app's own Apple-style look: it follows the visitor's light or dark setting,
chrome is neutral (black, white, grey) and colour (blue/orange, green) only ever means data. **Plain HTML, CSS and a little JavaScript. No build step, no framework, no cookies, no analytics.** Upload this
folder to any static host.

```
website/
  index.html            the home page (hero, how it works, features, deep dives, privacy, pricing, FAQ)
  download.html         download card, checksum, install steps, the "Unknown publisher" explainer
  terms.html  privacy.html  refunds.html     DRAFT legal pages (replace the [brackets], then have them reviewed)
  thanks.html           the page Stripe and Supabase send people back to (see "Return links")
  404.html  robots.txt  sitemap.xml  _headers
  site.config.js        the settings you will tweak most (name, price, support email, social links, section switches)
  assets/site.css       colours (tokens at the top, copied from the app), layout and effects
  assets/site.js        header/footer, download button, and the animated bits
  assets/release.json   the current release (filled by tools/sync_release.py; empty = "Coming soon")
  assets/og-image.png   the picture shown when the link is pasted into Discord/Reddit/X
  tools/                sync_release.py, set_domain.py, og-template.html
```

## Look at it
```
python -m http.server 8000 --directory website      # then open http://localhost:8000
```
(Opening `index.html` by double-click works for the look, but the download button reads `assets/release.json`, which
needs a server.)

## Tweaking it
| To change... | Edit |
|---|---|
| Product name, tagline, price text, support email, social links, which sections show | `site.config.js` |
| Colours, corner radius, fonts, motion | the `:root { ... }` tokens at the top of `assets/site.css`: the light values first, then the dark ones under `@media (prefers-color-scheme: dark)` (the app's palette; change one value and the whole site follows) |
| Headline, section text, FAQ answers, feature list | `index.html` (plain text, easy to find) |
| The animated replay in the hero (speed, colours, goal timing) | the `replay()` function in `assets/site.js` |
| The price on the page | `site.config.js` **and** `service.py` (`PRICE_TEXT`) **and** the price in Stripe: keep all three equal |
| The share image | edit `tools/og-template.html`, open it in a 1200x630 window, screenshot it over `assets/og-image.png` (headless: `msedge --headless=new --window-size=1200,630 --screenshot=og.png file:///.../tools/og-template.html`) |
| Real screenshots instead of the drawn mockups | drop images in `assets/` and swap them in for the `.mock` blocks (alt text required) |

Everything on the site that describes the product (40+ stats, 8 key-moment types, 8 rank bands, model sizes, the Free and
Pro split) was taken from the app itself. If the app changes, change the site's wording to match.

## Before it goes public (checklist)
- [ ] **Domain:** `python website/tools/set_domain.py yourdomain.com` (puts it in canonical links, share tags, sitemap,
      robots.txt and the support email). Then set `supportEmail` in `site.config.js` to a real inbox.
- [ ] **Legal pages:** fill in the `[Your name or company]`, `[Your country]`, `[date]`, `[Region]`, `[Email provider]` and
      `[Website and download host]` placeholders (`legalName` and `country` live in `site.config.js`), and get them reviewed.
- [ ] **Return links** (below) entered in Stripe and Supabase, and `TERMS_URL` / `PRIVACY_URL` / `SUPPORT_EMAIL` set in `service.py`.
- [ ] **A real release** published and `tools/sync_release.py` run (below). Until then every download button reads "Coming soon".
- [ ] Deployed, then check `https://yourdomain.com/` over HTTPS and that the response headers from `_headers` are present.

## Publishing a release to the download page
1. Build a **normal** release: `release.ps1` (without `-Demo`) and upload `dist/release/RLAnalyser-Setup-<version>.exe` somewhere
   public. GitHub Releases is the usual choice (many hosts cap file sizes, so keep the 60 MB installer off the site itself).
2. `python website/tools/sync_release.py --url https://github.com/<you>/<repo>/releases/download/v<version>/RLAnalyser-Setup-<version>.exe --installer dist/release/RLAnalyser-Setup-<version>.exe`
3. Redeploy the site.

`sync_release.py` **refuses a demo build** (its notes say DEMO) and any non-https address, and with `--installer` it checks the
file you uploaded matches the checksum in `latest.json`.

## Return links (what to give Stripe and Supabase)
One page, `thanks.html`, serves them all by its `?status=` value:

| Where | Address |
|---|---|
| Stripe Checkout success (`CHECKOUT_SUCCESS_URL`) | `https://yourdomain.com/thanks.html?status=paid` |
| Stripe Checkout cancel (`CHECKOUT_CANCEL_URL`) | `https://yourdomain.com/thanks.html?status=cancelled` |
| Billing portal return (`PORTAL_RETURN_URL`) | `https://yourdomain.com/thanks.html?status=portal` |
| Supabase Authentication, Site URL | `https://yourdomain.com/thanks.html?status=confirmed` |

## Hosting
Any static host works. Easiest options:
- **Cloudflare Pages** or **Netlify**: connect the repo (or drag the `website/` folder in), no build command, publish directory
  `website`. Both read `_headers`, which gives the site a strict Content-Security-Policy (no inline scripts or styles exist, so
  nothing breaks) plus the usual security headers. Add your domain in their dashboard; HTTPS is automatic.
- **GitHub Pages**: publishes a whole branch or `/docs`, not a sub-folder, so you'd deploy `website/` with a small Actions
  workflow. It **ignores `_headers`**, so you lose the extra security headers.

## Quality bar it was checked against
Every page at 1440 px and 390 px wide: no console errors under the strict CSP, no horizontal scrolling, one `h1` and ordered
headings, all internal links and `#anchors` resolve, nothing stays hidden after scrolling, animations stop under "reduce
motion", and Tab starts at "Skip to content" with a visible focus ring on everything.
