# Writing a theme

A theme is a folder under `themes/` that contains a `theme.json` and the PNG decorations it
uses. Iconbloom lists every such folder in its theme dropdown. You don't need to write any code.

```
themes/
  my_theme/
    theme.json
    star.png
    src/star.svg        # optional: editable source for the PNG
```

## theme.json

```json
{
  "name": "Mint Cream",
  "palette": {"light": "#E6FFF5", "main": "#8FE3C3", "ink": "#2F7A63", "cream": "#FFFDF7"},
  "assets": {"star": "star.png"},
  "recipes": [
    {"id": "mint_tint", "label": "Mint tint",
     "ops": [{"op": "tint", "stops": ["ink", "main", "light"]}]},
    {"id": "star_tile", "label": "Tile + star", "keeps_color": true,
     "ops": [{"op": "tile", "fill": "cream"},
             {"op": "badge", "asset": "star", "corner": "top-right"}]}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | Shown in the theme dropdown. |
| `palette` | Named colors as `#RRGGBB`. Recipes refer to colors by these names. |
| `assets` | Name to PNG file, relative to the theme folder. |
| `recipes` | The styles offered for each icon, in this order. |

Each recipe has an `id` (unique, used in file names), a `label` (shown under the preview) and
`ops`, a list of steps applied in order to the icon at 256 px. Set `keeps_color` to `true`
when the recipe shows the icon's own colors. Busy, colorful icons get those recipes first,
and simple glyphs get the others first.

## Colors

Wherever a color is expected, you can write:

- a palette name: `"main"`
- a hex color: `"#FFFFFF"`
- `"auto"`: the saturated palette color closest in hue to the icon, so a blue icon gets
  your blue-ish shade instead of a muddy one

## Ops

| Op | What it does | Parameters (defaults) |
|---|---|---|
| `tint` | Maps the icon's dark-to-light range onto color stops, darkest first | `stops` (required, 2+ colors), `strength` (1.0) |
| `soft_tint` | Pulls the icon toward one color but keeps a hint of its own hues | `color` (required), `amount` (0.45) |
| `mono` | Fills the icon with one color; contrasting inner details become see-through | `color` (required), `knockout` (true) |
| `gradient_fill` | Like `mono`, with a two-color gradient | `stops` (required, 2 colors), `angle` (90, top to bottom), `knockout` (true) |
| `tile` | Shrinks the icon onto a filled shape | `fill` (required, 1 color or 2 for a gradient), `shape` (`squircle`, `circle` or `rounded`), `angle` (90), `scale` (0.7), `shadow` (true), `outline` (none) |
| `sticker_outline` | Die-cut sticker border behind the icon | `thickness` (10 px), `color` (`#FFFFFF`), `shadow` (true) |
| `glow` | Soft halo around the icon | `color` (required), `radius` (10), `strength` (0.8) |
| `overlay_face` | Tiny face on the lower middle of the icon | `face` (required asset), `scale` (0.42), `offset_x` (0), `offset_y` (0.16) |
| `badge` | Decoration in a corner | `asset` (required), `corner` (`top-right`, `top-left`, `bottom-right`, `bottom-left` or `random`), `scale` (0.35), `rotation` (0) |

`overlay_face` and `badge` are left out of the 16 and 24 px icon sizes, where they would only
add noise.

## Shuffle

Any parameter written as a list, where one value is expected, is a set of choices. The default
look always uses the first choice. **Shuffle** picks among them at random:

```json
{"op": "badge", "asset": ["bow", "heart"], "corner": ["top-right", "top-left"]}
```

For color stops, a list of lists is a set of choices: `"stops": [["ink", "main"], ["ink", "accent"]]`.
Shuffle also nudges a few numbers slightly, such as the face position, badge rotation and
gradient angle.

## Decorations

Assets are transparent PNGs. Draw them yourself or use art you have the rights to share. Keep
an editable SVG in `src/` and render it with:

```bash
uv run python -m scripts.render_assets my_theme
```

## Checking your theme

Mistakes are reported when the theme loads, with the recipe, step and parameter named:

```
themes/my_theme/theme.json: recipe 'star_tile', step 2 (badge), 'asset': unknown asset 'starr'
```

Then render every recipe on the sample icons and look at the result at full and small sizes:

```bash
uv run python -m engine.sheet tests/samples --theme my_theme -o sheet.png
```
