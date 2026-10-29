# Rumbo logo

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="rumbo-wordmark-reversed.svg">
  <img src="rumbo-wordmark.svg" alt="rumbo" height="72">
</picture>
&nbsp;&nbsp;
<img src="rumbo-symbol.svg" alt="Rumbo symbol" height="72">

*Rumbo* is a ship's course, and the word English sailors borrowed as *rhumb line*:
a course held at one bearing. The logo is drawn in the board's chart language.

- **The symbol is `r···o`.** The r's shoulder turns into the course line. Three
  dots stand in for the letters between, u, m and b, the way the board's last
  leg stays dashed until someone decides. The line ends in a chart **fix**, a
  ring with a dot, in place of the o.
- **The fix is the owner's mark.** It uses the board's owner magenta. Agents
  extend the line; only the human owner closes it.
- **The wordmark spells the word in full**: a monoline geometric lowercase built
  from the same stroke and radius, with the same fix for its o.

## Files

| File | Use |
| --- | --- |
| `rumbo-symbol.svg` | App and listing icon. Also written to `rumbo/.claude-plugin/icon.svg` and `openai-plugin/rumbo/assets/icon.svg` |
| `rumbo-symbol-light.svg` | Icon on light surfaces that need a light tile |
| `rumbo-symbol-small.svg` | 32 px and below: one dot instead of three |
| `rumbo-symbol-mono.svg` | No tile; uses `currentColor`. Inline it so it takes the text color |
| `rumbo-wordmark.svg`, `rumbo-wordmark-reversed.svg` | The logo on light and dark backgrounds |
| `rumbo-symbol-512.png`, `rumbo-favicon-32.png` | Raster exports of the icon |
| `rumbo-social-1280x640.png` | Repository social preview |

`make_logo.py` draws every SVG here from its construction and writes the two
plugin icons. Change the geometry there, not in the SVG files:

```sh
python3 docs/brand/make_logo.py
```

The PNG files are rendered from the SVGs with Chromium.

## Color

| Name | Hex | Role |
| --- | --- | --- |
| Ink | `#12222E` | Letters on light; the icon tile. Same as the board's `--ink` |
| Paper | `#FAFCFC` | Letters on dark. Same as the board's `--paper` |
| Fix magenta | `#C42A78` | The fix on light backgrounds; the listing `brandColor` |
| Fix pink | `#EF72B3` | The fix on dark backgrounds and on the ink tile |

Fix magenta has 5.3:1 contrast on white and 3.0:1 on `#212121`. Fix pink has
6.0:1 on ink.

## Use

- Keep the o as the fix. Do not swap the magenta for another color or fill the ring.
- The fix is the only colored part. Do not color the r or the dots.
- Use the symbol when the space is square; use the wordmark otherwise. Do not set
  them side by side, because the fix would appear twice.
- Leave clear space of at least the ring's diameter around the wordmark.
