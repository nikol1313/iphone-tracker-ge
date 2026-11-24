# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Shoppers in Georgia who are about to buy an iPhone. Many arrive on a phone from a shared link (Facebook, Messenger) to one model's page. Their job: find which store sells the exact model, storage and color cheapest today, and decide whether to buy now or wait.

## Product Purpose

iPhone Tracker.ge compares iPhone prices across Georgian stores (Zoommer, Alta, iSpace, Elit Electronics, Megatechnica, Extra.ge, PCShop, Metromart, Gstore, Kontakt, iCity). Prices are collected from the stores' websites twice a day and every change is recorded. Success: a buyer knows the cheapest in-stock store and whether today's price is a good one within seconds.

## Positioning

It keeps the price history. Store sites show today's price; this site shows every store side by side plus how the price moved, so it can say "lowest in 30 days" or "buy now or wait".

## Operating Context

- Entry points: the Today page, a shared product link (`/iphone-17-pro-256gb-silver`) with server-filled social previews, search.
- Pages: Today (overview), All iPhones (catalog + product detail with history chart and per-store table), Compare (two phones spec by spec with a weighted pick), Watchlist (tracked products and price alerts by email), About.

## Capabilities and Constraints

- Georgian is the default language; English is the second. Long Georgian labels must fit at every width, down to 320px.
- Dark theme is the default; a light theme is available via a toggle.
- Vanilla HTML/CSS/JS served by FastAPI; no frontend framework or build step. Fonts are self-hosted (no requests to Google).
- Prices are in GEL (₾).

## Brand Commitments

- Name "iPhone Tracker.ge" with the amber ".ge", and the existing logo mark (`app/static/logo-mark.png`).
- Neutral: the site is not affiliated with any store and does not sell phones. Never style one store like an ad.

## Evidence on Hand

- Real live price data and history from the stores.
- Demo video: `app/static/iphone-tracker-demo.mp4`.
- No testimonials, press, or user counts exist; do not invent them.

## Product Principles

1. The price is the answer: the cheapest store and its price come first on every surface.
2. Earn trust with history, not adjectives: claims come from recorded data.
3. Fast on a phone: a shared link must answer the question on the first screen.
4. Neutral between stores.
