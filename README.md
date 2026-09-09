# 139 Design Studio — Daily Blog Automation

Automated daily blog post generation and publishing for 139aruba.com.

> **Status (2026-09-09):** The daily blog is now handled by Claude's scheduled task (6:00 AM Aruba time). This repository serves as a backup for the queue and style guide only. The GitHub Actions workflow has been removed; `blog_automation.py` is kept as a reference and does not run automatically.


---

## How It Works

- **Daily Trigger:** GitHub Action runs at 7:00 AM Aruba time (UTC-4)
- **Queue-Based:** Reads the next topic from `blog_topic_queue.md`
- **AI-Powered:** Generates content via Claude API (`claude-sonnet-5`)
- **WordPress Publish:** Builds the Elementor layout and publishes via the WordPress REST API (Application Password)
- **Self-Updating:** Moves the published topic to the `## Published` section of the queue and pushes the file

---

## Repository Structure



---

## Files

| File | Purpose |
|------|---------|
| `blog_topic_queue.md` | Dated topic table. Rows marked **PUBLISHED** are skipped |
| `blog_139aruba.md` | House style, layout recipe, image and SEO rules |
| `aruba_local_context.md` | Local facts every post must respect |
| `elementor_template.json` | Elementor layout cloned from an approved post, with placeholders |
| `blog_automation.py` | Python script that handles the entire workflow |
| `.github/workflows/daily_blog.yml` | Scheduled GitHub Action (7 AM Aruba time) |

---

## Secrets Required

Configure these in **Settings → Secrets and variables → Actions**:

| Secret Name | Purpose |
|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key for content generation |
| `WP_APP_PASSWORD` | WordPress application password for user `Mic139` |
| `PEXELS_API_KEY` | Optional. Enables fresh photography; without it the newest featured image in the category is reused |

---

## Category IDs

| Category | ID |
|----------|-----|
| Branding | 7 |
| E-commerce | 10 |
| Summit | 13 |
| Web development | 15 |
| Graphic design | 18 |
| Event | 24 |
| Amazon | 25 |
| AI | 30 |

---

## Local test

```bash
pip install anthropic requests
python blog_automation.py --check                  # parse the queue only
python blog_automation.py --dry-run                # generate, build, publish nothing
BLOG_POST_STATUS=draft python blog_automation.py   # publish as a draft for review
```

## Manual Run

To trigger the workflow manually:

1. Go to the **Actions** tab
2. Select **"Daily Blog Automation"**
3. Click **"Run workflow"**

---

## Notes

- WordPress user: `Mic139` (Application Password required)
- API model: `claude-sonnet-5` (override with `CLAUDE_MODEL`)
- The post is published immediately at run time. Note: WP-Cron was stalled on the site Aug 10-Sep 4, 2026, which is where this assumption came from; a cPanel cron job fixed it on Sep 4 and it has been publishing scheduled (`future`-status) posts correctly since — see the Claude scheduled task notes before assuming it's broken again
- Timezone: Aruba (AST / UTC-4)

---

**Created by:** Michael D. Tromp — 139 Design Studio
