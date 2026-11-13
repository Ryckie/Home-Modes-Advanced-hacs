# Brand images

Home Assistant 2026.3 and newer read brand images for a custom integration from a `brand/`
folder inside the integration. Local images take priority over the brands CDN and are served
by Home Assistant at `/api/brands/integration/home_modes/<file>`. HACS requires at least `icon.png`.

The mark is a house holding a four-position mode dial, with the active position lit. It is an
original design; do not use Home Assistant branded images. The SVG sources are in
[`docs/images/source/`](images/source/); the PNGs are rendered from them.

| File | Required size | Status in the repo |
|---|---|---|
| `custom_components/home_modes/brand/icon.png` | 256 × 256, square | done (256 × 256) |
| `custom_components/home_modes/brand/icon@2x.png` | 512 × 512 | done (512 × 512) |
| `custom_components/home_modes/brand/logo.png` | shortest side 128 to 256 | done (840 × 256) |
| `custom_components/home_modes/brand/logo@2x.png` | shortest side 256 to 512 | done (1680 × 512) |
| `custom_components/home_modes/brand/dark_logo.png` (+ `@2x`) | as above | done (light text for dark themes) |
| `dark_icon.png` (+ `@2x`) | as above | not provided: the icon works on both backgrounds |

The README banner (`docs/images/banner.png`, 1280 × 640) uses the same mark and also fits
GitHub's social preview (**Settings → General → Social preview**).

PNG, transparency preferred. `tests/test_release_files.py::test_brand_images_have_the_documented_sizes`
checks the sizes, so a replacement with the wrong size fails the tests.
Sources: HACS publish documentation (integration requirements) and the Home Assistant developer
documentation on brand images (UNVERIFIED in a real HA 2026.11 instance: no instance was available).
