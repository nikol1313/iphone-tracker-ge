---
name: iPhone Tracker.ge
description: iPhone price comparison for Georgian stores — every phone quoted like a listed stock, in warm ink on old paper.
colors:
  bg: "#1a1a19"
  surface: "#20201e"
  surface-2: "#2a2926"
  ink: "#e9e7e2"
  ink-2: "#a9a69e"
  muted: "#94918a"
  line: "#2e2d2a"
  line-strong: "#403e3a"
  accent: "#e9e7e2"
  on-accent: "#1a1a19"
  amber: "#f2b84b"
  good: "#9cc58a"
  good-soft: "#232a1f"
  rise: "#e07a62"
  warn: "#f2b84b"
  warn-soft: "#2d2618"
  blue: "#84afe3"
  photo: "#ebe8e1"
  light-bg: "#f1eee7"
  light-surface: "#f7f5f0"
  light-surface-2: "#e7e3da"
  light-ink: "#1a1a19"
  light-ink-2: "#4f4c46"
  light-muted: "#625f57"
  light-line: "#ddd8cd"
  light-good: "#4e7a3e"
  light-rise: "#b5452c"
  light-amber: "#b07a12"
typography:
  quote-price:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "4rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.035em"
  page-title:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.03em"
  section-title:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
  column-title:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 600
  body:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  table:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 500
  meta:
    fontFamily: "Instrument Sans, Noto Sans Georgian, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 400
rounded:
  tag: "4px"
  control: "6px"
  panel: "8px"
  dialog: "12px"
spacing:
  wide: "1240px"
  column: "760px"
  gutter: "24px"
  row: "36px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    height: "42px"
    padding: "0 22px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 16px"
  nav-tab-active:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
  topbar:
    backgroundColor: "{colors.surface}"
    height: "58px"
  store-row-best:
    backgroundColor: "{colors.good-soft}"
    textColor: "{colors.good}"
    height: "36px"
  chart-panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "14px 16px"
  product-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "12px"
  tag:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.tag}"
    padding: "2px 8px"
  dialog:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.dialog}"
---

# DESIGN.md

## Overview

Market quote page. Every iPhone is quoted like a listed stock: today's best price as the big figure, its signed move, every store in a ruled table with its place on today's spread, and the price line beside it. It's an Operate surface: dense, aligned, calm, standard controls. The palette is warm ink on old paper: nothing pure black or white, every tone leans warm. Dark is the default; the light theme is warm paper. Source of truth: `app/static/css/base.css` (tokens), `shell.css`, `catalog.css`, `overlays.css`, `responsive.css`. Direction contract: `.impeccable/surfaces/app-static-index-html.md`.

## Colors

- Warm neutrals (`bg`, `surface`, `surface-2`, `ink`, `ink-2`, `muted`) carry the page. `muted` is the floor for readable metadata (≥4.5:1 on every surface in both themes); don't add a dimmer gray.
- `good` (muted green) = cheaper, cheapest, price down; `rise` (muted terracotta red) = pricier, price up. Price meaning only.
- `amber` is the small-touch accent: the ".ge" mark, focus ring and text selection, chart points, the profile avatar, selected cards and options, catalog tags, link underlines on hover, the compare pick heading. In the light theme amber is for marks and large text, not body copy.
- `accent` (paper white in dark, ink in light) is the primary button.
- Store photos sit on `photo` with `mix-blend-mode: multiply`.

## Typography

- One family: Instrument Sans, with Noto Sans Georgian for Georgian. Tabular figures on the body. The serif note voice is retired; `--serif` aliases the sans.
- Fixed rem scale, no fluid type. Rank comes from weight first, size second: the quote price (4rem/700) is the only large figure on a page.
- Headline sentences put the price last (`… at {store}: {price}`), so the price can sit on its own line.

## Layout

- One wide container (1240px) with 24px gutters. Today: quote header, then a work area (store table ≤600px | chart panel), then three equal columns (24h moves, weekly drops, per model) via `repeat(auto-fit, minmax(300px, 1fr))`.
- Table rows are 36px; separators are hairlines (`line`), and groups are split by a full-width rule.
- Breakpoints: 1020px (nav drops below the bar, the work area stacks), 700px (phone: price 3rem, 14px gutters), 420px (smallest phones, wordmark hidden).

## Elevation & Depth

- Flat. The top bar is a solid `surface` panel with a `line-strong` bottom rule (no blur). Panels use a 1px `line` border. Only floating overlays (menus, suggestions, dialogs, toast) carry `--shadow`.

## Shapes

- Rectangular: 6px controls (buttons, inputs, selects, chips, nav tabs), 4px tags, 8px panels and cards, 12px dialogs. No pills; the avatar is a 4px rounded square.
- State is shown by a tint plus text colour, never a side stripe.

## Components

- **Today lists**: name + variant chips, price, then one meta line with the move (or stock count). No store name; colours of one phone that moved alike share a row.
- **Nav tabs**: muted text; the active tab is a `surface-2` block with a 2px inset ink underline.
- **Quote header**: sentence (1.1rem, `ink-2`) → price span `.intro-price` → signed change badge `.intro-change` (green tint for down, red tint for up) → counts line.
- **Store table**: one size, rank by weight; the cheapest rows are tinted `good-soft` with the price in `good`. The last cell is the **spread bar** (signature): a 6px track with a 3px ink marker at the store's position between today's cheapest (0%) and priciest (100%), green on the cheapest rows. It slides in once on load.
- **Chart**: inline SVG in a `surface` panel; ink step line drawn with `pencil-draw`, ink point blots; SVG `<text>` never takes the icon stroke.
- **Motion**: 150–250ms state changes; one authored moment per page load, the headline price counting down from the 30-day high to today's price (900ms, ease-out-quart). All motion is off under `prefers-reduced-motion`.

## Do's and Don'ts

- Do lead every surface with the cheapest store and its price.
- Do keep stores visually equal; no store gets a colour or ad styling.
- Do keep green and red for price meaning only.
- Do keep the Today lists (24h moves, weekly drops, per model) free of store names: phone, variant, price and move only. The store lives in the store table and on the phone page.
- Don't add pills, serif notes, eyebrow labels, gradient text, glows, or side stripes.
- Don't add a second large figure competing with the quote price.
