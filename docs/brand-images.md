# Brand images

Home Assistant 2026.3 and newer read brand images for a custom integration from a `brand/`
folder inside the integration. Local images take priority over the brands CDN and are served
by Home Assistant at `/api/brands/integration/home_modes/<file>`. HACS requires at least `icon.png`.

**The files in the repository are placeholders** (grey boxes marked "PLACEHOLDER / REPLACE ME").
They ship with the v0.9.0 beta as placeholders and **must be replaced before 1.0**. Do not use Home Assistant branded images.

| File | Required size | Status in the repo |
|---|---|---|
| `custom_components/home_modes/brand/icon.png` | 256 × 256, square | placeholder (256 × 256) |
| `custom_components/home_modes/brand/icon@2x.png` | 512 × 512 | placeholder (512 × 512) |
| `custom_components/home_modes/brand/logo.png` | shortest side 128 to 256 | placeholder (512 × 256: the shortest side is 256) |
| `custom_components/home_modes/brand/logo@2x.png` | shortest side 256 to 512 | placeholder (1024 × 512: the shortest side is 512) |
| `dark_icon.png`, `dark_logo.png` (+ `@2x`) | as above | not provided (optional) |

PNG, transparency preferred. `tests/test_release_files.py::test_brand_images_have_the_documented_sizes`
checks the sizes, so a replacement with the wrong size fails the tests.
Sources: HACS publish documentation (integration requirements) and the Home Assistant developer
documentation on brand images (UNVERIFIED in a real HA 2026.11 instance: no instance was available).
