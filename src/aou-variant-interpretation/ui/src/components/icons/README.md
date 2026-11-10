# Icons

The UI's icon set: one component per icon, all drawn to the same rules so they read as one
family at any size. Every icon goes through `baseIconProps` in `Icon.tsx`, which supplies the
grid, the stroke and the colour; an icon file holds only its paths.

Three drawings are deliberately not part of the set and keep their own SVG: the favicon
(`public/favicon.svg`), `LensSpinner` and `PhenotypeFilterIllustration`. They are brand marks
and illustrations, not UI icons.

## The rules

1. **One grid.** 24 units, square, `viewBox="0 0 24 24"`. No icon is ever non-square; `size`
   sets width and height together.

2. **Draw to the keyline.** Geometry sits inside the square from 2 to 22, so with its stroke the
   mark fills 1 to 23. A ring is `r="10"` at the centre. Small symbols (arrows, plus, cross,
   chevrons, check) sit on the inner square from 4 to 20, or 5 to 19 for a cross, so they read
   lighter than objects. Measure a new icon before merging: a drawing a unit or two inside the
   keyline looks smaller than its neighbours at the same pixel size.

3. **Stroke only.** 2 units, round caps and joins, `currentColor`. No fills, and no second
   weight inside an icon. A dot is a zero-length stroke (`M12 8h.01`), which round caps draw as a
   disc. A solid shape means "selected"; that is the job of the thing around the icon, not the
   icon.

4. **Corners are 2.** Boxes and lids round at `rx="2"` or an `a2 2` arc. Never 1.

5. **Nothing finer than 2 units.** Parallel strokes stay 2 units apart, no feature is shorter
   than 2, and an icon has at most four inner marks. At 11px a unit is under half a pixel, so
   detail that needs more is a drawing, not an icon.

6. **Weight follows size, automatically.** `baseIconProps` picks the stroke from the rendered
   size: 2.5 at 12px and under, 2.25 at 13 to 15, 2 at 16 and up (`strokeWidthFor`). Call sites
   pass `size` only. Pass `strokeWidth` only to break the rule on purpose, with a comment saying
   why.

7. **Six sizes.** 11 for figures inline with 11 to 12px text, 12 for small buttons, 14 beside
   13px labels and in buttons, 16 in lists and navigation, 18 for the top bar's controls, 20 for
   a panel header. Don't introduce 10, 13 or 15.

8. **Take it from Lucide first.** If [Lucide](https://lucide.dev) has the icon, use its paths
   unchanged; they already obey rules 1 to 5. Draw by hand only for what it lacks, and measure the
   result against the keyline.

9. **Decorative by default.** An icon beside a label is `aria-hidden="true"`; an icon on its own
   gets its name from the button or link around it, never from the SVG.

## Adding an icon

1. Create `NameIcon.tsx` from an existing one: import `baseIconProps` and `IconProps`, spread
   `baseIconProps(props)` onto the `<svg>`, and put the paths inside. No attributes on the `<svg>`
   beyond the spread.
2. Export it from `index.ts`.
3. Check it on the grid beside its neighbours at 16px and 11px. The quickest way is to drop it
   into a scratch page with the keyline square (2 to 22) drawn behind it.

## Why these rules

The set was reviewed in October 2026. Its contract (grid, stroke, colour) was already shared,
but half the icons had been drawn a unit or two smaller than the rest, two used a corner radius
of 1, three carried fills or private stroke weights, and the stroke weight was chosen by hand at
each of 27 call sites. The rules above are what that review settled on, and the redraw that came
with it brought every icon onto the keyline and took the weights out of the call sites.
