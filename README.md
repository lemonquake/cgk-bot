# CGK Linens Discord Bot

A management Discord Bot built for CGK Linens.
Created by Aljay Leodones.

---

## What This Bot Does

This bot provides server management and announcement tools for the CGK Linens Discord community. It includes a persistent **Mod Panel** summoned with `/summon` that stays active even after bot restarts.

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
```
*(Note: If you want slash commands to appear instantly in a specific test server while developing, paste your Server/Guild ID in `GUILD_ID`)*.

#### Step 11: Start the Bot
Run the bot with:
```bash
python3 main.py
```
You will see output indicating that the bot has connected:
```
[INFO] cgk_bot: Registering persistent views...
[INFO] cgk_bot: Loading extensions...
[INFO] cgk_bot: Synced 1 global command(s).
[INFO] cgk_bot: ==========================================
[INFO] cgk_bot: Logged in as: CGK Bot (ID: ...)
[INFO] cgk_bot: Bot is active in 1 server(s)
[INFO] cgk_bot: ==========================================
```

---

### Phase 3: Using the Bot

#### Step 12: Summon the Mod Panel
1. Go to any text channel in your Discord server where you have moderator/admin permissions.
2. Type `/summon` and press Enter.
3. The **CGK Linens Management Panel** will appear with:
   - Live Server Information (Server Name and Member Count)
   - Real-time Bot Latency / Status
   - Interactive Buttons:
     - **📝 Embed Message** (Announcements builder)
     - **💬 Normal Message** (Plain text sender)
     - **🔄 Refresh Dashboard** (Live update of server stats and feature list)

#### Step 13: Persistent Controls
- You do **not** need to run `/summon` again when the bot restarts.
- Clicking **🔄 Refresh Dashboard** on any existing panel will automatically refresh its data and confirm connection.

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
├── config.py             # Global constants and brand theme
├── main.py               # Main bot launcher and persistent view registration
├── cogs/
│   ├── __init__.py
│   └── mod_panel.py      # /summon slash command
├── views/
│   ├── __init__.py
│   └── mod_panel_view.py # Persistent buttons and embed layout
└── README.md             # Documentation and guide
```

---

## Credits

Created by **Aljay Leodones** for **CGK Linens**.
