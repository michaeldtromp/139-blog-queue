# 139 Design Studio — daily blog run (139aruba.com/news/)

This repository is the source of truth for the daily post queue. Every run, whether from a desktop Claude session or an unattended task, follows this order:

1. **Date.** Aruba is UTC-4 with no daylight saving: `TZ=America/Aruba date +%F`.
2. **Read** `blog_topic_queue.md`, find today's row, skip anything marked **PUBLISHED**.
3. **Read** `blog_139aruba.md` (house style, Elementor recipe, image rules, SEO step) and `aruba_local_context.md` (local facts; never storm or hurricane content).
4. **Check WordPress for an existing draft first.** Search posts of any status for today's title before writing a new one, so a re-run never duplicates a post. (WP-Cron was stalled Aug 10-Sep 4, 2026 and left `future`-status posts unpublished during that window; a cPanel cron job fixed it on Sep 4 and scheduled posts have gone live on their own since — this step is a safety net, not an expected regular occurrence.)
5. **Build and publish** via the Novamira connector for 139aruba.com (`mcp__novamira-139aruba-com__mcp-adapter-execute-ability`, ability `novamira/execute-php`). It authenticates as WordPress user 2 (Mic139) and needs no password. Clone the layout of the newest published post's `_elementor_data`; run the AIOSEO update; publish with `wp_update_post` and purge LiteSpeed.
6. **Images:** convert locally with `sips` (hero 1200x900 JPEG, in-body 1200x675 JPEG), upload with `novamira/create-upload-link` + `curl PUT`, register with `wp_insert_attachment`, patch `_elementor_data` with `wp_slash`, regenerate CSS with `\Elementor\Core\Files\CSS\Post::create($id)->update()`.
7. **Mark the row** `— **PUBLISHED** (post <id>)` in `blog_topic_queue.md`.
8. **Commit and push:** `git add blog_topic_queue.md && git commit -m "Publish YYYY-MM-DD: <title> (post <id>)" && git push origin main`.
9. **Report** title, post ID, live URL, preview URL `https://139aruba.com/?p=<id>&preview=true`, and confirm the push.

Event and summit posts: the reader is a visitor, never an exhibitor, sponsor or stand designer. Verify every date and link on the organiser's site at write time.

The unattended path is Claude's scheduled task (06:00 Aruba). The GitHub Actions workflow was removed on 2026-09-09 to avoid double publishing; `blog_automation.py` stays in the repo as a reference and can be run by hand with `--dry-run` or `--check`. Whoever publishes a post must mark its row PUBLISHED in `blog_topic_queue.md` and push, so the next run does not repeat it.
