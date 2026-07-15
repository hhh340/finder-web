# No-Website Finder

Type an area, neighbourhood, city or postcode anywhere in the **US, Canada or UK**, and get a
list of every small business there (restaurants, cafes, barbers, salons, shops, repair services…)
that has **no website** — or whose only web presence is a Facebook / Instagram / Linktree page or
a directory listing (Yelp, DoorDash, Booksy…). Great for finding web-design leads.

## Run it

**Option A — hosted (GitHub Pages), no install at all:**
enable Pages on this repo (Settings → Pages → Deploy from a branch → `main`, folder `/docs`)
and open the published URL. The page calls the Nominatim / Overpass / Google APIs directly from
your browser. Paste your Google API key into the key field once — it's kept in that browser's
localStorage. Tip: restrict the key to your Pages URL (HTTP referrer) in the Google Cloud console.

**Option B — locally:**

```bash
python3 server.py
```

Then open **http://localhost:4173**. No installs needed — pure Python standard library. In this
mode the key can also live in `google_api_key.txt` next to `server.py` so you never paste it.

## How to use

1. Type an area (e.g. `Camden Town, London` or `Kitsilano, Vancouver` or `78704 Austin`),
   click **Find area**, and pick the right match.
2. Pick a radius.
3. Pick a data source:
   - **Google Places API (accurate)** — the recommended mode. Your API key lives in
     `google_api_key.txt` next to `server.py` (already set up) and is picked up automatically —
     the UI shows "✓ loaded from google_api_key.txt". You can also paste a key into the UI field
     to override it. To make a new key: https://console.cloud.google.com/google/maps-apis, enable
     **Places API (New)**. Tick the business categories you want, then search.
     "Deep" mode sweeps a grid of sub-areas for bigger coverage (uses more API requests —
     the UI shows an estimate first; Google's free monthly tier covers thousands of requests).
   - **OpenStreetMap (free)** — no key needed, pulls every named business in one go. Less
     reliable: OSM volunteers often don't record a website even when a business has one, so
     treat its "no website" results as unverified leads.
4. Filter results with the chips (**No website / Social only / Directory only / Has website**),
   use the text filter, click **Search** links to double-check a business on Google, and
   **Export CSV** to save the filtered list.

## How "no website" is decided

- **Google mode:** businesses put their web presence in their Google Business Profile — this is
  what shows as the "Website" button on Google Maps. If the field is empty → *No website*. If it
  points at facebook.com / instagram.com / linktr.ee / TikTok / WhatsApp → *Social only*. If it
  points at Yelp, DoorDash, UberEats, Booksy, Fresha, etc. → *Directory/ordering only*.
  All three groups are leads.
- **OSM mode:** same classification using OSM's `website` / `contact:*` tags.

## Notes & limits

- Scraping Google Maps, Facebook or Instagram directly is against their terms of service, so this
  tool uses the official Places API and OpenStreetMap instead. A business that runs *only* on
  Facebook/Instagram almost always links that page as its "website" on Google Maps, which is how
  the *Social only* bucket catches them.
- Google Text Search returns at most 60 results per query — that's why the Google mode searches
  per-category (and per-grid-cell in Deep mode). For a whole city, run several searches over
  different neighbourhoods and merge the CSVs.
- Overpass (the free OSM server) is a shared public service and sometimes times out on very dense
  areas — just retry, or use a smaller radius.
