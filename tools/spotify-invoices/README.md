# Spotify Invoice Fetcher

Downloads Spotify subscription receipts/invoices using the internal account API.

## Prerequisites

You need a valid `sp_dc` cookie from an authenticated Spotify browser session.

### Getting your `sp_dc` cookie

1. Log in to [open.spotify.com](https://open.spotify.com) in your browser
2. Open Developer Tools (F12) → Application → Cookies → `https://open.spotify.com`
3. Copy the value of the `sp_dc` cookie

> **Note:** The cookie expires periodically. If you get auth errors, get a fresh one.

## Usage

```bash
# Set the cookie
export SPOTIFY_SP_DC="your-cookie-value-here"

# List available orders
python tools/spotify-invoices/fetch_invoices.py --list-only

# Download all invoices to data/raw
python tools/spotify-invoices/fetch_invoices.py --output-dir data/raw

# Or pass cookie directly
python tools/spotify-invoices/fetch_invoices.py --sp-dc "AQXYZ..." --output-dir data/raw
```

## How it works

1. Authenticates with Spotify using the `sp_dc` session cookie
2. Fetches order history from `https://www.spotify.com/api/account-settings/v1/orders`
3. Downloads receipt PDFs for each order
4. Saves files as `YYYY_MM_DD_spotify.pdf` in the output directory

Files are then ready to be processed by the compta-auto pipeline (rename, metadata extraction, etc.).

## Integration with compta-auto

After downloading, run a folder scan to process the invoices:

```bash
compta-auto scan  # if invoices land in the watched folder
```

Or import them manually via the web UI at http://localhost:8765.
