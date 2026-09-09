---
name: blog-139aruba
description: How to build and publish posts on the 139aruba.com /news/ blog — connector choice, Elementor recipe, image rules, SEO step and house style.
type: project
---

# 139aruba.com news blog

Blog index: https://139aruba.com/news/ — style reference post: `how-to-start-a-web-design-business-in-14-practical-steps` (id 26962).

**Post 27506 is the approved template.** Michael signed off on it 2026-09-03 ("Beautiful!") and said to keep the same style for all further posts. Clone 27506's structure, length, tone and image treatment rather than reinventing.

## Connector choice — Novamira FIRST, WPVibe fallback
Michael's standing preference, confirmed 2026-09-03. **Novamira has no daily call cap; WPVibe's free plan does** (300/day until 2026-09-09, then 100/day — a single post build costs 15-25 calls and the cap was hit on 2026-09-03).

- Interactive work: use `mcp__remote-devices__novamira-139aruba-com__mcp-adapter-execute-ability` with `ability_name` + `parameters`. Verified working 2026-09-03 (`aioseo-posts/seo-data-get` returned correctly). The same 53 abilities WPVibe exposes are reachable here — AIOSEO, WPForms, core, plus `novamira/execute-php` for anything the abilities don't cover.
- **CRITICAL CONSTRAINT: Novamira is proxied through Michael's Mac** (`mcp__remote-devices__*` = the desktop bridge). A cloud-only scheduled task has NO access to it. The daily blog task runs in the cloud (`local_device_not_required`), so it must keep using WPVibe unless the task is recreated as device-bound — and a binding cannot be added to an existing task, only set at creation.
- So: **Novamira for interactive sessions, WPVibe for the unattended daily run.** Do not "fix" this by pointing the cloud task at Novamira; it will simply fail.

## Site facts
- Posts are **Elementor** documents (legacy Section/Column, not Containers). `_elementor_edit_mode=builder`, `_elementor_template_type=wp-post`.
- Build via WPVibe `rest_api` POST `/wpvibe/v1/elementor/save-page` with `post_type:"post"`, `template_type:"wp-post"`, `page_template:"elementor_header_footer"` (reproduces the reference layout exactly — verified 2026-09-03).
- `wp eval`, `list_files`, `get_preview_url` are **blocked** (DISALLOW_FILE_EDIT). Preview a draft at `https://139aruba.com/?p=<id>&preview=true` in Michael's Chrome (he stays logged in).
- **WP-Cron is disabled** — see [[wp-cron-139aruba]]. Scheduled posts never publish on their own.
- Media: WPVibe `upload_media` sideloads from a **public URL** — an Adobe `photoshop-api.adobe.io/v2/short-url/...` output URL works directly. To push a local file, use Claude-in-Chrome: `/wp-admin/media-new.php?browser-uploader`, `find` the file input, `file_upload` from `/mnt/user-data/outputs/`, click Upload.
- Container egress **blocks** `stock-apex-images-prod-*.s3.*.amazonaws.com` — never curl a licensed Stock file; pipe it through Adobe's `image_crop_and_resize` and hand the output URL to `upload_media`.
- Category IDs: web-development 15, AI 30, graphic-design 18, e-commerce 10, branding 7, event 24, summit 13, amazon 25. All posts use tag id 5. Author id 2.
- All 8 categories were given real descriptions on 2026-09-03; they become the archive meta descriptions.

## Images — Michael's rules (he rejected two attempts, 2026-09-03)
Hard rules:
- **Real, candid documentary photography only. NEVER a typographic title card / poster graphic with text on it.**
- **NEVER a laptop or device with a blank or white screen.** Mockup shots are an instant reject.
- Avoid glossy tech/AI stock clichés (holograms, glowing circuits, robot hands) and posed corporate smiling-at-camera shots.
Positive direction:
- Warm natural light, real people at work in real spaces, shallow depth of field, muted editorial tone, candid side or over-the-shoulder framing.
- Reference images: `Web-Design-Tips-News-blog_139.jpg` (barista behind a café counter, 2021), `News-blog_139-Web-dev-2024.jpg` (person at a laptop in a yellow-walled office, 2024).
Per post:
- **1 hero photo at 1200x900, plus 1-2 in-body photos at 1200x675.** In-body images go immediately before an `<h2>`, inserted into the body text-editor HTML as `<figure style='margin:10px 0 30px 0'><img src='…' alt='…' style='width:100%;height:auto;display:block' /></figure>`. Single-quoted HTML attributes so nothing needs escaping in the JSON patch.
- Pick in-body photos that match the section they precede.

## Image toolchain — Adobe Stock + Magnific
- **Adobe Stock sources.** `asset_search` with `entityScope: "StockAsset"`. Keep queries SHORT (3-6 words) — long queries and the `orientation` filter both return zero hits, so filter landscape by comparing width/height yourself.
- **Vet thumbnails visually before showing him.** `asset_inline_preview` refuses `t3/t4.ftcdn.net` and Claude-in-Chrome blocks that domain, but the **built-in browser (Claude_Browser) loads ftcdn fine** — navigate + screenshot there, then present only vetted candidates with `asset_preview_file`.
- His selections in the `asset_preview_file` widget do NOT reach Claude — ask him to reply with the number/ID.
- Working pipeline: `asset_license_and_download_stock` → `image_crop_and_resize` (fit `reframe`, `focus: {prompt: "…"}`, explicit w/h, outputFileType jpeg) → `asset_inline_preview` to verify the crop → `upload_media` with the Adobe output URL → set `featured_media` and/or patch `_elementor_data`.
- **Magnific stays in the toolkit** (he pays for it, https://www.magnific.com/app). No connector exists; drive magnific.com/app through Claude-in-Chrome. It is an upscaler/enhancer, not a source — for cleaning up a small client photo or one of his own shots.

## Layout recipe (copy from post 27506)
1. Hero section: dark polygonal bg (media id 25241) + gradient overlay, 50/50 columns, `reverse_order_mobile`. Left = h1 heading (Inter, 300 weight, uppercase, letter-spacing -1.5), text-editor "Posted <date> under <category link>", `elementskit-social-share` (LI FB X WA TG). Right = image widget (hero photo).
2. Body section: 65/35 columns, 1px right border on the left column. Left = drop-cap text-editor intro (Inter 24/28) + main text-editor with `<h2>` + `<ul>` + inline `<figure>` images + closing h4 CTA heading + a text-editor with the CTA link and an italic *Sources:* line. Right = "Recent Posts" heading (Space Grotesk 130px uppercase) + `elementskit-blog-posts` (`num:2`, `offset:1`) + absolute spacer glow.
3. All widgets carry `_animation:"fadeIn"` — content is invisible until scrolled into view, so scroll before screenshotting a preview.
4. To edit text or images later, patch `_elementor_data` via `/wpvibe/v1/content/edit` (target_type `meta`) anchored on a unique string. Slashes are stored escaped, so an `<h2>` anchor reads `<h2>Heading<\/h2>`. Apply the same edit to `post_content` too, or AIOSEO scores stale text.

## SEO — never skip it, Michael checks
Run `aioseo-posts/seo-data-update` with `postId` and set `focus_keyphrase`, `title` (under 60 chars, keyphrase at the START), `description` (140-155 chars with the keyphrase), `additional_keyphrases`, and the four `social` fields. The keyphrase must genuinely appear in the SEO title, slug, meta description, first paragraph, at least one H2, at least one image alt, and 4+ times in the body. TruSEO recalculates in the editor, not on save — post 27506 went 60 → 82 once the content matched. All 10 older posts were given keyphrases and rewritten descriptions on 2026-09-03.

## House style
- H2s render uppercase via the kit; write them sentence case.
- Bulleted lists with `<strong>` lead-ins, then one or two explanatory sentences.
- Intro is one punchy hook + a hard, sourced statistic.
- Always close with an Aruba/local angle, a practical checklist, and a CTA to https://139aruba.com/contact/.
- Cite real sources with links in an italic *Sources:* line. Research first, write second.
- Link internally to an older 139aruba.com post whenever genuinely relevant.
- 800-1,100 words. Read [[aruba-local-context]] before writing any local angle.

## Daily posting plan
- Seven days a week, one post per date — see [[blog-topic-queue]] for the dated queue through 2026-10-13.
- Random publish time between 08:00 and 18:00 Aruba, different each day, delivered by a one-shot Claude task because WP-Cron is dead.
- Recurring task: `trig_01APuYPqe96b1vUrRkCFXTKQ` "Daily 139aruba.com blog post", fires 10:00 UTC (06:00 Aruba) daily, cloud-only.
