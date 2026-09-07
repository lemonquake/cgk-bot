# CGK Linens Discord Bot

A management Discord Bot built for CGK Linens.
Created by Aljay Leodones.

---

## What This Bot Does

This bot provides server management, announcement, onboarding, and member engagement tools for the CGK Linens Discord community. It includes a persistent **Mod Panel** summoned with `/summon` that stays active even after bot restarts.

Three systems power it:

| System | What it does |
| --- | --- |
| **Member Onboarding** | Scans for members who joined recently and were never welcomed, lets you pick **which join days** to include, then posts a tagged welcome and sends each member a warm branded DM. Everyone welcomed is logged so nobody is welcomed twice. |
| **Community Reports** | Daily growth baselines, joins per day, monthly trends and most-active members. Deploy one public report and it refreshes itself in place every few hours. |
| **Engagement Reports** | Ranks every member by messages, reactions and threads for any date range, published as a formal summary plus a full text file. |
| **Engagement Contest** | Automated contest scoring across select channels (3 pts message, 1 pt reaction, 5 pts TikTok video post) with mod/bot exclusions, date range selection, and Top 15 leaderboard. |

All of it is driven from the Mod Panel — no commands to memorise.

---

## Step-by-Step Installation & Setup Guide

Follow these numbered steps to set up and run the bot.

---

### Phase 1: Discord Developer Portal Setup

#### Step 1: Open the Discord Developer Portal
1. Open your web browser and go to: [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Log in with your Discord account.

#### Step 2: Select or Create Your Bot Application
1. Click the **"New Application"** button in the top-right corner (or click your existing application if already created).
2. Give your application a name (for example, `CGK Linens Bot`) and agree to the Discord Developer terms.
3. Click **Create**.

#### Step 3: Enable Privileged Gateway Intents (Very Important)
1. In the left sidebar, click on **"Bot"**.
2. Scroll down to the section titled **"Privileged Gateway Intents"**.
3. Turn **ON** (check) all three switches:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**
4. Click **"Save Changes"** at the bottom of the page.

#### Step 4: Get Your Bot Token
1. On the same **"Bot"** page, find the **"Token"** section.
2. Click **"Reset Token"** (or **"Copy"** if freshly generated).
3. Copy this token. This is the secret password for your bot.

#### Step 5: Create the Bot Invite Link
1. In the left sidebar, click on **"OAuth2"**, then click on **"URL Generator"**.
2. Under **"Scopes"**, check these two boxes:
   - `bot`
   - `applications.commands` (this enables slash commands like `/summon`)
3. Under **"Bot Permissions"**, check:
   - `Administrator` (or select `Manage Server`, `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`).
   - For engagement reports without Administrator access, grant `View Channels` and `Read Message History` in every channel that should be analyzed, plus `Send Messages`, `Embed Links`, and `Attach Files` in the report channel.
4. Scroll to the bottom and click **"Copy"** next to the **Generated URL**.

#### Step 6: Invite the Bot to Your Discord Server
1. Paste the copied URL into a new tab in your web browser.
2. Select your Discord server from the dropdown list.
3. Click **"Continue"**, then click **"Authorize"**.
4. Complete the verification check. The bot will now appear in your server member list.

---

### Phase 2: Running the Bot on Your Computer

### Quick Start Launchers (Easiest Way to Run)

- **On Mac:** Simply double-click [`start_bot.command`](file:///Users/lemonquake/Engines/cgk-bot/start_bot.command). It automatically checks the virtual environment, verifies requirements, and starts the bot.
- **On Windows:** Simply double-click [`start_bot.cmd`](file:///Users/lemonquake/Engines/cgk-bot/start_bot.cmd).

---

### Manual Terminal Setup (Step-by-Step)

#### Step 7: Open Your Terminal
Open the Terminal application on your computer and navigate to the project directory:
```bash
cd /Users/lemonquake/Engines/cgk-bot
```

#### Step 8: Set Up Python Virtual Environment
Create and activate a virtual environment to manage dependencies cleanly:
```bash
python3 -m venv venv
source venv/bin/activate
```

#### Step 9: Install Required Dependencies
Install the required packages (`discord.py` and `python-dotenv`):
```bash
pip install -r requirements.txt
```

#### Step 10: Configure Your `.env` File
1. Make sure you have a `.env` file in the project root directory.
2. Open `.env` and add your bot token:
```env
DISCORD_TOKEN=your_token_here
GUILD_ID=
REPORT_CHANNEL_ID=1541562452993511584
REPORT_TIMEZONE=Asia/Manila
```
*(Note: If you want slash commands to appear instantly in a specific test server while developing, paste your Server/Guild ID in `GUILD_ID`)*.

Everything else is optional — see [`.env.example`](.env.example) for the full list:

| Setting | Default | Purpose |
| --- | --- | --- |
| `WELCOME_CHANNEL_ID` | *(blank)* | Starting value for the welcome post channel. |
| `ONBOARDING_CHANNEL_ID` | *(blank)* | The "start here" channel linked in welcomes. |
| `INTRODUCTIONS_CHANNEL_ID` | *(blank)* | The introductions channel linked in welcomes. |
| `ONBOARDING_LOOKBACK_DAYS` | `30` | How far back the onboarding scan looks. |
| `REPORT_REFRESH_HOURS` | `3` | How often live community reports refresh. |
| `ENABLE_PRESENCE_INTENT` | `true` | Tracks "online now"; the bot starts without it automatically if the portal switch is off. |
| `COMMUNITY_DATABASE_PATH` | `data/community.sqlite3` | Onboarding log, growth snapshots, live reports. |

You never have to edit `.env` for the three onboarding channels — set them in Discord from **Mod Panel → Onboarding → Channel setup**, and those saved choices always win.

#### Step 11: Start the Bot
Run the bot with:
```bash
python3 main.py
```
You will see output indicating that the bot has connected:
```
[INFO] cgk_bot: Registering persistent views...
[INFO] cgk_bot: Loading extensions...
[INFO] cgk_bot.engagement: Engagement tracking database ready at data/engagement.sqlite3
[INFO] cgk_bot.database: Community database ready at data/community.sqlite3
[INFO] cgk_bot.onboarding: Onboarding ready (lookback: 30 days)
[INFO] cgk_bot.memberreport: Community reporting ready (live reports refresh every 3h)
[INFO] cgk_bot: Synced 3 global command(s).
[INFO] cgk_bot: ==========================================
[INFO] cgk_bot: Logged in as: CGK Bot (ID: ...)
[INFO] cgk_bot: Bot is active in 1 server(s)
[INFO] cgk_bot: Presence tracking: on
[INFO] cgk_bot: ==========================================
```

---

### Phase 3: Using the Bot

#### Step 12: Summon the Mod Panel
1. Go to any text channel in your Discord server where you have moderator/admin permissions.
2. Type `/summon` and press Enter.
3. The **CGK Linens Management Panel** appears with live server info, bot latency, an onboarding snapshot, your live reports, a plain-English guide to every button, and a system health block.
4. Buttons on the panel:

| Button | What it opens |
| --- | --- |
| **👋 Onboarding** | Scan for new members, pick which join days, send the welcome, set your channels. |
| **📊 Community Reports** | Preview or deploy self-refreshing growth reports. |
| **📈 Engagement Report** | Rank members by messages, reactions and threads. |
| **🏆 Engagement Contest** | Launch Top 15 contest leaderboard in designated channels with TikTok & point weighting. |
| **📝 Embed Message** | Open the Embed Studio: compose, save reusable templates, and publish to any channel. |
| **💬 Normal Message** | Send a plain text message through the bot. |
| **🔄 Refresh Dashboard** | Reload the panel with the latest data **and the latest buttons**. |

> Already have an older panel posted? Just click **🔄 Refresh Dashboard** on it once — it upgrades that message to the new button set in place.

Two optional shortcuts post standalone panels for teams that prefer them: `/onboarding` and `/community-report`. Both are persistent, just like `/summon`.

---

#### Step 13: Welcome New Members (Onboarding)

1. On the Mod Panel click **👋 Onboarding**.
2. First time only — click **⚙️ Channel setup** and pick three channels from the dropdowns:
   - **Welcome / announcements** — where the public welcome post goes.
   - **Start here (onboarding)** — linked in every welcome.
   - **Introductions** — linked in every welcome.
   Each choice saves instantly and survives restarts.
3. Click **🔍 Scan for new members**. The bot lists everyone who joined in the last 30 days and was never welcomed, grouped by join day:
   ```
   ▸ Joined today — 4 member(s)
   ▸ Joined yesterday — 2 member(s)
   ▸ Joined 3 days ago — 1 member(s)
   ▸ Joined 1 week ago — 9 member(s)
   ```
4. **Select which days** you want in the dropdown. It is a multi-select — pick one day, several days, or **Everyone not yet welcomed**. The embed updates with the exact members selected as you go.
5. Choose how to write it:
   - **⚡ Send default welcome** — uses the ready-made CGK Linens message.
   - **✍️ Write my own message** — opens an editor pre-filled with the default so you can tweak it.
6. Review the preview, then choose the delivery:
   - **📣 Post publicly + warm DM** (recommended)
   - **📢 Post publicly only**
   - **✉️ Warm DM only**
7. Pick the channel (or click **⭐ Use my saved welcome channel**) and the bot:
   - posts one message tagging every selected member,
   - DMs each member a branded welcome with clickable links to your onboarding and introductions channels,
   - logs them as onboarded so the next scan skips them.

Notes:
- DMs are paced at **one per second** to respect Discord's rate limits, so 40 members takes about 40 seconds. The summary reports how many DMs landed and who has DMs closed.
- **📋 Onboarding stats** shows how many members are waiting, how many were welcomed this week, and the all-time total.
- **♻️ Reset onboarding log** clears the log if you ever want to welcome people again.

Placeholders you can use in any message (welcome posts, embeds, plain messages):

```
{user_mention}  {user_name}  {server_name}  {member_count}  {date_now}
{time_now}  {brand}  {onboarding_channel}  {introductions_channel}  {welcome_channel}
```

---

#### Step 14: Deploy a Community Report

1. On the Mod Panel click **📊 Community Reports**.
2. **Select which days** the report covers: today, 7 days, 14 days, 30 days, 90 days, or **Custom number of days** (anything from 1 to 365).
3. Then either:
   - **👀 Preview a report** — private, nothing is posted; or
   - **📌 Deploy live report** — pick a channel and the report goes public.
4. A deployed report **refreshes itself in place** every 3 hours (`REPORT_REFRESH_HOURS`) and on every bot start. You never repost it.
5. **🔄 Refresh now** updates every live report immediately. **🗂️ Manage live reports** stops one from refreshing (the posted message stays).

Each report shows:
- **Membership growth** — total, members, bots and online now, each compared to the stored baseline from that many days ago, with the arrow and percentage change.
- **New members per day** — a 14-day bar chart.
- **Joins trend** — monthly totals plus this month versus the same point last month.
- **Most active members** — top contributors for the window, taken from the engagement tracker.
- **Server snapshot** — members, bots, team/admins and online count.

How the numbers stay accurate:
- A baseline snapshot is recorded at **00:05 UTC** every day, on every refresh, and whenever a report is built.
- Join tallies come from live join events **and** are re-derived from every member's join date on each refresh, merged with `MAX()`. Nothing is lost while the bot is offline.
- "Online now" needs the **Presence Intent**. If that switch is off in the Developer Portal the bot notices, starts without it, and hides just that one metric.

---

#### Step 15: Generate an Engagement Report
1. Open the Mod Panel and click **📈 Engagement Report**.
2. Choose **Past 1 day**, **Past 7 days**, **Past 1 month**, or **Custom date range**.
3. For a custom range, enter `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`. Date-only end dates include the complete end day.
4. The bot publishes a formal summary and full ranked text report to `REPORT_CHANNEL_ID`.

The tracker counts each non-bot member's messages, reactions added, and threads created. Each action is one activity point. Reports rank up to 300 members in servers with 300 or fewer members, or up to 1,000 members in larger servers. Before publishing, the bot backfills every readable text channel and active or archived thread for the selected period. Large date ranges can take a few minutes. Discord does not expose historical reaction timestamps, so backfilled reaction totals represent reactions currently visible on messages posted during the selected period; live reaction events use their actual event time.

---

#### Step 16: Compose and Reuse Embeds (Embed Studio)

1. On the Mod Panel click **📝 Embed Message**. The **Embed Studio** opens privately, showing your current draft, the server's template library and the placeholders you can use.
2. Click **✏️ Edit embed** and fill in whatever you need — every field is optional on its own:
   - **Title**
   - **Message** (the embed body)
   - **Text above the embed** — for a ping or a short intro, e.g. `<@&role>`
   - **Image URL** — must start with `http://` or `https://`
   - **Colour hex** — blank for CGK navy, or e.g. `C8A96A`
3. Save it for next time with **💾 Save as template** and give it a name (up to 60 characters). If that name is already taken the bot shows who last changed it and asks before replacing anything.
4. To reuse a template later, pick it from the **📂 Load a saved template** dropdown. It drops straight into the draft, ready to edit or publish. With more than 25 templates the dropdown pages with **◀️ / ▶️**.
5. While a template is loaded the studio tracks whether the draft still matches it:
   - **✅ saved** — the draft and the template are identical.
   - **⚠️ unsaved changes** — click **🔄 Update "name"** to store your edits back into that template.
6. **🗂️ Manage templates** lists everything saved with how often each one was used, when it changed and who changed it. From there you can **📂 Load**, **✏️ Rename** or **🗑️ Delete** (deleting always asks first, and never touches your draft).
7. **👁️ Preview & publish** shows the finished message with every placeholder filled in, then publishes it to the channel you pick. The studio stays open behind the preview.
8. **🧹 New draft** starts a blank message (saved templates are kept), and **✖️ Close** puts the studio away.

Reliability notes:
- **Your draft is auto-saved after every change.** Close the window, let the panel time out or restart the bot — reopening **📝 Embed Message** brings the same draft back, still linked to its template.
- **Templates are per server and shared with the team.** Anyone with **Manage Server** can load, update or delete them, and the library survives restarts because it lives in `data/community.sqlite3`.
- **Names are unique per server, ignoring case.** `Restock` and `restock` are the same template, and extra spaces are tidied away, so the list never fills up with near-duplicates.
- **Every server keeps up to 100 templates.** Delete one you no longer use to make room.
- Bad data is repaired rather than crashing the composer: an image link Discord would reject is dropped with a warning, an over-long body is trimmed, an invalid colour falls back to CGK navy, and a template whose stored data cannot be read is flagged with ⚠️ in the list so you can re-save over it.

---

#### Step 17: Persistent Controls
- You do **not** need to run `/summon` again when the bot restarts. Every button carries a fixed ID and is re-registered on startup.
- The same is true for the standalone `/onboarding` and `/community-report` panels.
- Clicking **🔄 Refresh Dashboard** on any existing panel refreshes its data and its button set.

---

## Project Structure

```
cgk-bot/
├── .env                  # Private configuration containing bot token (git ignored)
├── .env.example          # Safe template for configuration
├── .gitignore            # Keeps private files out of Git
├── requirements.txt      # Python dependencies
├── start_bot.command     # 1-Click launcher for macOS
├── start_bot.cmd         # 1-Click launcher for Windows
├── config.py             # Global constants, brand theme and palette
├── main.py               # Launcher, persistent view registration, intent fallback
├── core/
│   ├── __init__.py
│   ├── database.py       # Async SQLite store (onboarding, snapshots, reports, settings, templates)
│   ├── embed_script.py   # Placeholder hydration + broadcast message state
│   └── embed_templates.py # Saved embed template library and auto-saved drafts
├── utils/
│   ├── __init__.py
│   └── embed_builder.py  # Unified embed design system, deltas, ANSI status blocks
├── cogs/
│   ├── __init__.py
│   ├── engagement.py     # Activity tracking, SQLite ledger, ranked reports
│   ├── memberreport.py   # Growth snapshots, join tallies, self-refreshing reports
│   ├── onboarding.py     # Member scanning, welcome posts, warm DMs, onboarding log
│   └── mod_panel.py      # /summon, /onboarding, /community-report
├── views/
│   ├── __init__.py
│   ├── broadcast_view.py         # Embed + plain message composers
│   ├── common.py                 # Permission guards shared by every panel
│   ├── embed_studio_view.py      # Embed Studio: draft, template library, publish
│   ├── engagement_report_view.py # Activity period and custom date controls
│   ├── member_report_view.py     # Day picker, deploy, refresh, manage
│   ├── mod_panel_view.py         # Persistent Mod Panel buttons and embed
│   └── onboarding_view.py        # Scan, join-day multi-select, composer, delivery
├── data/                 # Runtime databases (git ignored)
└── README.md             # Documentation and guide
```

### Database Tables

`data/community.sqlite3`

| Table | Purpose |
| --- | --- |
| `onboarded_members` | Who was welcomed, when, by which moderator. |
| `member_snapshots` | One growth baseline per server per UTC day. |
| `member_joins` | Join counts per day and per week. |
| `member_reports` | Deployed live reports and their refresh state. |
| `guild_settings` | Channel choices made from the Mod Panel. |
| `embed_templates` | Saved embed templates, one unique name per server. |
| `embed_drafts` | Each moderator's auto-saved Embed Studio draft. |

`data/engagement.sqlite3`

| Table | Purpose |
| --- | --- |
| `activity_events` | One row per message, reaction or thread, de-duplicated. |
| `engagement_metadata` | When live tracking began. |

---

## Credits

Created by **Aljay Leodones** for **CGK Linens**.
