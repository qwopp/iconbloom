# Writing a theme

A theme is a folder under `themes/` that contains a `theme.json` and the PNG decorations it
uses. Iconbloom lists every such folder in its theme dropdown. You don't need to write any code.

```
themes/
  _library/
    recipes.json        # recipes shared by every theme
    decorations/*.svg   # bow, heart, star, flower, cloud, moon, leaf, sun...
  my_theme/
    theme.json
    star.png            # rendered from _library/decorations/star.svg
```

## theme.json

```json
{
  "name": "Mint Cream",
  "palette": {
    "light": "#E6FFF5", "main": "#8FE3C3", "deep": "#4FB58E", "ink": "#2F7A63",
    "accent": "#F6C3D5", "peach": "#F2D47A", "cream": "#FFFDF7"
  },
  "decor": {"fill": "#8FE3C3", "outline": "#2F7A63", "eye": "#2E3B33", "blush": "#F59AB0"},
  "assets": {"star": "star.png"},
  "recipes": [
    "pastel_tint",
    {"use": "bubble_cream", "label": "Cream bubble"},
    {"id": "star_tile", "label": "Dotty tile + star", "family": "pattern",
     "ops": [{"op": "tile", "fill": "cream", "pattern": "dots", "pattern_color": "main"},
             {"op": "badge", "asset": "star", "corner": "top-right"}]}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | Shown in the theme dropdown. |
| `palette` | Named colors as `#RRGGBB`. Recipes refer to colors by these names. |
| `decor` | Colors for the decoration drawings (see [Decorations](#decorations)). |
| `assets` | Name to PNG file, relative to the theme folder. |
| `recipes` | The styles offered for each icon, in this order. |

A recipe is one of:

- a library id, such as `"pastel_tint"`: the recipe from `_library/recipes.json`, drawn in
  this theme's palette
- `{"use": "<library id>", "id": ..., "label": ...}`: a library recipe under another id or label
- a full recipe object

A full recipe has an `id` (unique, used in file names), a `label` (shown under the preview), a
`family` and `ops`, a list of steps applied in order to the icon at 256 px. Keep a recipe's
`id` once the theme has shipped: people's saved choices refer to it.

## The library

`_library/recipes.json` holds the shared recipes; read it for the ids. They are written in
seven palette names, so a theme that uses them defines all seven:

| Name | Role |
|---|---|
| `light` | palest tint, for tiles and highlights |
| `main` | the theme's signature color |
| `deep` | a stronger shade of `main` |
| `ink` | darkest shade, for outlines and the dark end of tints |
| `accent` | a second hue |
| `peach` | a third hue |
| `cream` | the plain tile color (dark in a dark theme) |

Some library recipes also add decorations, so their themes list these `assets`: `bow`,
`heart`, `sparkle`, `star` and `face`.

## Order and families

Styles appear in the order the theme lists them. Put the most striking first, and don't put
two of the same `family` next to each other:

| Family | For recipes that |
|---|---|
| `recolor` | keep the icon's color regions but swap in theme colors |
| `gradient` | paint the icon one color on a gradient tile |
| `mono` | paint the icon one color |
| `tile` | put the icon on a plain tile |
| `pattern` | put the icon on a patterned tile |
| `sticker` | add a die-cut sticker border |
| `tint` | map the icon onto a few theme shades |
| `glow` | tint the icon and add a halo |
| `cutout` | cut a logo out of its plain background (start with `remove_background`) |

For busy, colorful icons, `tint` and `glow` recipes move toward the end, since flattening
many colors into a few shades loses the most there. `cutout` recipes always come last, and
are left out for icons that have no plain background to cut.

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
| `recolor` | Gives each of the icon's hues its own shade from the stops: separate color blocks stay separate, smooth gradients stay smooth, and grays stay neutral | `stops` (required, 2+ colors), `strength` (1.0) |
| `soft_tint` | Pulls the icon toward one color but keeps a hint of its own hues | `color` (required), `amount` (0.45) |
| `mono` | Fills the icon with one color; contrasting inner details become see-through | `color` (required), `knockout` (true) |
| `duotone` | Paints the icon's main tone and its contrasting details two flat colors. A color left out takes the other part's own color, so with neither the two swap (a white logo with pink lines becomes pink with white lines) | `body`, `detail` (both optional) |
| `gradient_fill` | Like `mono`, with a two-color gradient | `stops` (required, 2 colors), `angle` (90, top to bottom), `knockout` (true) |
| `tile` | Shrinks the icon onto a filled shape | `fill` (required, 1 color or 2 for a gradient), `shape` (`squircle`, `circle` or `rounded`), `angle` (90), `scale` (0.7), `shadow` (true), `outline` (none), `pattern` (none, or `dots`, `stripes`, `gingham`, `hearts`), `pattern_color` (`#FFFFFF`) |
| `sticker_outline` | Die-cut sticker border behind the icon | `thickness` (10 px), `color` (`#FFFFFF`), `shadow` (true) |
| `glow` | Soft halo around the icon | `color` (required), `radius` (10), `strength` (0.8) |
| `overlay_face` | Tiny face on the lower middle of the icon | `face` (required asset), `scale` (0.42), `offset_x` (0), `offset_y` (0.16) |
| `remove_background` | Cuts away a plain plate behind a logo (a colored square or circle), keeping the logo, re-centered. Icons without one are left as they are | none |
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

The drawings in `_library/decorations/` are SVG templates. Their colors are tokens, filled
from the theme's `decor` colors, so one bow drawing becomes a pink bow or a mint one:

| Token | Used for |
|---|---|
| `fill`, `fill_dark`, `fill_deep` | main body, darker parts (bow tails, knot, sun rays) |
| `outline` | outlines and leaf veins |
| `shine` | soft highlights, flower and sparkle centers |
| `deep`, `accent` | the two sparkle outlines, and the moon's star |
| `blush`, `eye` | cheeks and eyes on the faces |

Set the tokens your decorations use; rendering names any that are missing.

List the decorations a theme uses under `assets`, then render them:

```bash
uv run python -m scripts.render_assets my_theme
```

Each PNG is rendered from the template of the same name. To draw your own, put an SVG in
`my_theme/src/`: it is used instead of the template of the same name. Draw it yourself or use
art you have the rights to share. A test fails if a committed PNG doesn't match its SVG.

## Checking your theme

Mistakes are reported when the theme loads, with the recipe, step and parameter named:

```
themes/my_theme/theme.json: recipe 'star_tile', step 2 (badge), 'asset': unknown asset 'starr'
```

Then render every recipe on the sample icons, and on a few real app icons if you have them,
and look at the result at full and small sizes:

```bash
uv run python -m engine.sheet tests/samples --theme my_theme -o sheet.png
```
