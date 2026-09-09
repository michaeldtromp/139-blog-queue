# 139 Design Studio — Daily Blog Automation

Automated daily blog post generation and publishing for 139aruba.com.

---

## How It Works

- **Daily Trigger:** GitHub Action runs at 7:00 AM Aruba time (UTC-4)
- **Queue-Based:** Reads the next topic from `blog_topic_queue.md`
- **AI-Powered:** Generates content via Claude API (`claude-sonnet-5`)
- **WordPress Publish:** Creates and schedules the post via REST API
- **Self-Updating:** Removes published topic from the queue and pushes the updated file

---

## Repository Structure



---

## Files

| File | Purpose |
|------|---------|
| `blog_topic_queue.md` | List of topics in order. Format: `YYYY-MM-DD Title — Category ID` |
| `blog_automation.py` | Python script that handles the entire workflow |
| `.github/workflows/daily_blog.yml` | Scheduled GitHub Action (7 AM Aruba time) |

---

## Secrets Required

Configure these in **Settings → Secrets and variables → Actions**:

| Secret Name | Purpose |
|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key for content generation |
| `WP_APP_PASSWORD` | WordPress application password for authentication |

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

## Manual Run

To trigger the workflow manually:

1. Go to the **Actions** tab
2. Select **"Daily Blog Automation"**
3. Click **"Run workflow"**

---

## Notes

- WordPress user: `Mic139` (Application Password required)
- API model: `claude-sonnet-5`
- Timezone: Aruba (AST / UTC-4)

---

**Created by:** Michael D. Tromp — 139 Design Studio
