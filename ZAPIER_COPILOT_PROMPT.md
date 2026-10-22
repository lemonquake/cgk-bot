# Zapier Copilot prompt — CGK Linens auto-onboarding

Paste everything below the line into Zapier Copilot. If Copilot cuts it off,
paste **Shared context** first, then each Zap section one at a time.

---

## Shared context (read before building any Zap)

Build a Discord onboarding system for the **CGK Linens** Discord server. It
replaces our current bot flow. There is **no "START MY ONBOARDING" button**
any more: a member joining the server starts everything automatically.

Every message text in this prompt is **verbatim**. Copy it character for
character, including emojis, `**bold**`, `## headings`, line breaks and the
`—` em dashes. Only replace the `{{placeholders}}`. Do not rewrite, shorten or
"improve" any member-facing text.

### Fixed IDs

| What | ID |
|---|---|
| Server (guild) | `1377020906441932800` |
| Channel that gets the "go to your channel" notice | `1377020906987065416` |
| Category the private onboarding channels go in | `1557840609664958599` |
| Access role (granted when onboarding is finished) | `1534216662415573023` |
| "Onboarding" role (removed when onboarding is finished) | `1559649034598227968` |
| Onboarding moderator role (can see every onboarding channel) | `1542915539872125049` |
| #🛍️tiktok-shop-101 channel | `1557490449160085615` |
| #opportunities-to-earn channel | `1557773483243741226` |

Brand color for embeds: `1783389` (hex `#1B365D`).

### Platform rules

1. **Join trigger:** use the Discord **New User Added** trigger. Skip bots.
2. **Anything Discord has no built-in action for** (create a channel with
   permission overwrites, send a message with buttons, add or remove a role,
   check a channel exists): use **Discord → API Request (Beta)** against
   `https://discord.com/api/v10`. If I tell you to post as our own CGK bot,
   use **Webhooks by Zapier → Custom Request** with the header
   `Authorization: Bot {{CGK_BOT_TOKEN}}` instead. I will enter the token
   myself; never put it in a message, a sheet or a log.
3. **Buttons:** Zapier cannot receive Discord button clicks, so every button
   in our flow becomes a Discord **link button** (component `type: 2`,
   `style: 5`, with a `url`, and the same `label` and `emoji` as below).
   Each link points to the Zap 2 catch hook (or the Zap 3 form) with the
   member's ID and secret token in the query string, so clicking it moves
   that member to the next step.
4. **Mentions:** every message sends `allowed_mentions` that pings only the
   member it is meant for (`{"parse": [], "users": ["{{user_id}}"]}`), or
   nobody (`{"parse": []}`) where the text says so. Never ping roles,
   @everyone or @here.
5. **State:** keep one row per member in a **Zapier Table** called
   `CGK Onboarding State` (see Zap 1). Every Zap looks the member up there
   first.
6. **Google Sheet:** the team reads the Google Sheet described at the end.
   Write Discord IDs, phone numbers and other number-like answers as plain
   text (prefix the value with `'`) so Sheets doesn't round 19-digit IDs,
   turn `04/25` into a date or run `=...` as a formula.

### Message rendering

- `{{mention}}` = `<@{{user_id}}>`
- `{{channel}}` = `<#{{channel_id}}>` (Discord shows it as a clickable channel link)
- "Hook link" = `{{ZAP2_HOOK_URL}}?u={{user_id}}&t={{token}}&a=<action>`
- "Form link" = the Zap 3 form URL with `u={{user_id}}` and `t={{token}}`
  prefilled into hidden fields

---

## Zap 1 — New member joins: open their channel and tag them

**Trigger:** Discord → New User Added (server `1377020906441932800`). Stop if
the user is a bot.

**Step 1 — Look up the member** in `CGK Onboarding State` by `discord_user_id`.

- If a row exists **and** its `channel_id` still exists in Discord
  (`GET /channels/{{channel_id}}` returns 200): reuse that channel. Skip to
  step 4 (re-post the welcome there) and step 5 (re-send the notice). Do not
  create a second channel.
- Otherwise continue.

**Step 2 — Make the channel name and token** (Code by Zapier or Formatter):

- `channel_name` = the member's **username** (handle, not display name),
  lowercased, every run of characters other than `a-z 0-9 _ -` replaced by
  `-`, leading/trailing `-` and `_` trimmed, cut to 80 characters, then
  `-onboarding` appended. Example: `Lemon.Tea` → `lemon-tea-onboarding`. If
  nothing is left, use `member-{{user_id}}-onboarding`.
- `token` = a random 32-character hex string (new for each member).

**Step 3 — Create the private channel:** `POST /guilds/1377020906441932800/channels`

```json
{
  "name": "{{channel_name}}",
  "type": 0,
  "parent_id": "1557840609664958599",
  "topic": "Private CGK onboarding for {{username}} · member ID {{user_id}}",
  "permission_overwrites": [
    {"id": "1377020906441932800", "type": 0, "deny": "1024"},
    {"id": "{{user_id}}", "type": 1, "allow": "117760"},
    {"id": "1542915539872125049", "type": 0, "allow": "68608"},
    {"id": "{{BOT_USER_ID}}", "type": 1, "allow": "84992"}
  ]
}
```

(`1024` = View Channel; `117760` = View, Send, Embed Links, Attach Files, Read
History; `68608` = View, Send, Read History; `84992` = View, Send, Embed Links,
Read History. `{{BOT_USER_ID}}` is whichever bot posts the messages. Server
admins can always see the channel.)

Save the new channel's `id` as `channel_id`, then create or update the member's
row in `CGK Onboarding State`:

| Field | Value |
|---|---|
| `discord_user_id` | member ID (text) |
| `discord_username` | member username |
| `channel_id` | new channel ID (text) |
| `token` | token from step 2 |
| `joined_at` | now, UTC |
| `is_creator` | empty |
| `journey` | empty |
| `finished_101` | `No` |
| `status` | `Channel opened` |
| `submitted_at` | empty |

**Step 4 — Tag the member in their channel:** `POST /channels/{{channel_id}}/messages`
(pings the member only).

Content, verbatim:

```
{{mention}} 🔒 This is your private onboarding channel — only you and the CGK team can see it. **Finish the onboarding below to unlock all of the server's channels.** Got a question along the way? Just type it here and the team will reply.

👋 Welcome to the CGK Linens Creator Community!

We're glad you're here. Before we get you set up, we have one quick question:

**Are you a TikTok Shop creator?**
```

Buttons (one row, link buttons):

| Label | Emoji | URL |
|---|---|---|
| `YES` | ✅ | Hook link with `a=yes` |
| `NO` | ❌ | Hook link with `a=no` |

**Step 5 — Point them to it from the shared channel:** at the same time,
`POST /channels/1377020906987065416/messages` — a normal text message, no
buttons, pings the member only. Verbatim:

```
{{mention}} Your private onboarding channel is ready: {{channel}}. Follow the steps there to get full server access.
```

**Step 6 — Google Sheet:** add or update the member's row on the **Members**
tab (see "Google Sheet" below) with Status `Channel opened`.

If channel creation fails (category full at 50 channels, missing permissions,
etc.), do not post anything to the member. Write Status `Needs attention` and
the error in the Notes column, and alert the team (email or a Discord message
to a staff channel I'll choose).

---

## Zap 2 — Button clicks (YES / NO / journey / finished TikTok Shop 101)

**Trigger:** Webhooks by Zapier → Catch Hook (accepts GET; the member's
browser opens the link). Query parameters: `u` (member ID), `t` (token), `a`
(action).

**Step 1 — Check the click:** look up `u` in `CGK Onboarding State`. Stop
silently if there is no row, `t` doesn't match the row's `token`, or `a` is not
one of `yes`, `no`, `learning`, `experienced`, `finished_101`.

**Step 2 — Paths by `a`.** Every path posts to the member's own channel
(`channel_id` from the row) and pings nobody (`{"parse": []}`).

### Path `no` → not a creator yet

Post verbatim, with link previews suppressed (`flags: 4`):

```
No worries! TikTok Shop is a great way to earn commission just by posting videos about products you love.

**Here's how to get started:**

1. Download TikTok and create an account if you haven't already
2. Grow your account to at least 1,000 followers to qualify for TikTok Shop
3. Apply to become a TikTok Shop affiliate in the app or at [shop.tiktok.com](http://shop.tiktok.com)
4. Once you're approved, come back, and we'd love to have you in the community!
```

No buttons. Update state: `is_creator` = `No`, `journey` = empty, `status` =
`Not a creator yet`. Update the Members tab to match.

### Path `yes` → journey question

Post verbatim:

```
Welcome! One more quick question so we can point you in the right direction:
**Where are you in your TikTok Shop journey?**
```

Buttons (link buttons, one per row):

| Label | Emoji | URL |
|---|---|---|
| `Still learning the ropes (requesting samples, filming, editing, etc.)` | 🌱 | Hook link with `a=learning` |
| `Experienced and ready to create` | 🔥 | Hook link with `a=experienced` |

Update state: `is_creator` = `Yes`, `journey` = empty, `status` =
`Answered YES`. Update the Members tab.

### Path `learning` → TikTok Shop 101

Post verbatim:

```
We'd love to help you hit the ground running! Head to [#🛍️tiktok-shop-101](https://discord.com/channels/1377020906441932800/1557490449160085615) to get everything you need to get started with TikTok Shop and CGK. Once you've gone through it, you'll be guided to the next step!
```

Button (link button):

| Label | Emoji | URL |
|---|---|---|
| `I've finished TikTok Shop 101` | ✅ | Hook link with `a=finished_101` |

Update state: `is_creator` = `Yes`, `journey` = `Still learning`, `status` =
`In TikTok Shop 101`. Update the Members tab.

### Paths `experienced` and `finished_101` → rules + questionnaire

Both send the same message. For `experienced` set `is_creator` = `Yes`,
`journey` = `Experienced`. For `finished_101` set `finished_101` = `Yes` and
leave `journey` as `Still learning`. Both set `status` = `Questionnaire sent`.
Update the Members tab.

Post **one** message with this content, verbatim:

```
## Ready to start earning with CGK? 💰 Here's a quick rundown of how this community works, what we expect from each other, and all the ways you can make money with us.

**Community Rules**
1. Respect others. No hate speech, discrimination, or bullying.
2. Keep chats organized. Use the right channels and avoid spamming.
3. Be an active participant. This community grows when everyone contributes. Share what's working, engage with other creators, and help each other level up.
4. For support, open a ticket in https://discord.com/channels/1377020906441932800/1545095961989353482. We do not respond to DMs for support requests.

By joining, you agree to follow these rules.

## Complete Your Onboarding 👇
```

…plus this embed in the same message (color `1783389`):

- **Title:** `Welcome to CGK Linens`
- **Description**, verbatim:

```
Click **Start onboarding** to complete your member questionnaire.

1. What's your TikTok handle?
2. What's your email?
3. What's your phone number?

Your answers are saved privately and shared only with our team. They won't be posted in this Discord channel. All three questions are required.
```

…plus one link button:

| Label | Emoji | URL |
|---|---|---|
| `Start onboarding` | none | Form link (Zap 3) |

If `status` is already `Completed`, skip all of this and post instead:

```
You've already submitted your onboarding answers. Contact a moderator if you need to correct them.
```

Clicking the same button twice just posts that step's message again. That is
expected.

---

## Zap 3 — Questionnaire submitted: save to the Sheet and unlock the server

### The form

Build a **Zapier Interfaces** form titled `CGK Linens onboarding`, with hidden
fields `u` and `t` prefilled from the URL. If Interfaces can't prefill hidden
fields from the URL, tell me and use a Google Form with a prefilled link
instead.

Three required fields, in this order:

| Key | Label | Placeholder | Max length |
|---|---|---|---|
| `tt_handle` | `What's your TT handle?` | `@yourhandle` | 100 |
| `email` | `What's your email?` | `name@example.com` | 254 |
| `phone` | `What's your phone number?` | `Include your country code, e.g. +1 555 123 4567` | 30 |

### The Zap

**Trigger:** new form submission.

**Step 1 — Check it:** look up `u` in `CGK Onboarding State`. Stop silently if
there is no row or `t` doesn't match the token. If `status` is already
`Completed`, post this to the member's channel (pings nobody) and stop:

```
You've already submitted your onboarding answers. Contact a moderator if you need to correct them.
```

**Step 2 — Validate.** Trim spaces from every answer first. Check in this
order and stop at the first failure:

| Check | Message (verbatim) |
|---|---|
| Any answer longer than its max length | `An answer is too long. Please shorten it.` |
| Any answer empty | `Please answer all three required questions.` |
| Email doesn't match `^[^\s@]+@[^\s@]+\.[^\s@]+$` | `Please enter a valid email address, such as name@example.com.` |
| Phone contains anything other than digits, spaces, `( ) + . -`, **or** has fewer than 7 or more than 15 digits | `Please enter a valid phone number, such as +1 555 123 4567.` |

On a failure, post the message to the member's channel (pings nobody) with a
link button labelled `Edit answers` that reopens the form with their answers
prefilled. Do not save anything, and stop.

**Step 3 — Save to the Google Sheet:** add a row to the **Onboarding
Responses** tab and update the member's row on the **Members** tab (see
below). `Submission ID` = the Zap run ID.

**Step 4 — Unlock the server:**

- `PUT /guilds/1377020906441932800/members/{{user_id}}/roles/1534216662415573023`
  (add the access role)
- `DELETE /guilds/1377020906441932800/members/{{user_id}}/roles/1559649034598227968`
  (remove the Onboarding role; ignore "unknown role" or "member doesn't have it")

**Step 5 — Tell the member** in their channel (pings nobody).

If both role changes worked, post verbatim, set state `status` = `Completed`
and `submitted_at` = now, and set Members-tab Status to `Completed`:

```
You now have full access to the CGK creator community! Head to [#opportunities-to-earn](https://discord.com/channels/1377020906441932800/1557773483243741226) to see all the ways you can earn with us. 🎉
```

If either role change failed, post verbatim, set state `status` =
`Needs attention`, and write the error on the Members tab:

```
✅ Thank you! Your answers are saved and our team has them. We couldn't unlock the rest of the server automatically — our team will give you access shortly.

⚠️ Onboarding roles could not be updated for {{mention}} — a moderator needs to check the access role and remove the Onboarding role.
```

The answers stay saved in the Sheet either way.

---

## Google Sheet — "CGK Onboarding"

Create (or use the one I pick) a spreadsheet with two tabs. Freeze and bold
the header row on both. Format the date columns as `yyyy-mm-dd hh:mm:ss`
(UTC). Write every ID, handle and phone number as text (leading `'`).

### Tab 1: `Onboarding Responses` — one row per submitted questionnaire

| Column | Value |
|---|---|
| Submitted (UTC) | submission time |
| TikTok handle | `tt_handle` |
| Email | `email` |
| Phone number | `phone` |
| TikTok Shop creator | `is_creator` from state |
| Journey | `journey` from state (`Experienced` / `Still learning`) |
| Discord account | username |
| Discord user ID | member ID |
| Discord server ID | `1377020906441932800` |
| Onboarding channel | `https://discord.com/channels/1377020906441932800/{{channel_id}}` |
| Access granted | `Yes` / `No` |
| Submission ID | Zap run ID |

### Tab 2: `Members` — one row per member who joined, kept up to date

Look the row up by **Discord user ID**, then update it; add it if missing.

| Column | Value |
|---|---|
| Joined (UTC) | `joined_at` |
| Discord account | username |
| Discord user ID | member ID |
| Onboarding channel | channel link (as above) |
| TikTok Shop creator | `Yes` / `No` / empty |
| Journey | `Experienced` / `Still learning` / empty |
| Finished TikTok Shop 101 | `Yes` / `No` |
| Status | `Channel opened` → `Answered YES` / `Not a creator yet` → `In TikTok Shop 101` → `Questionnaire sent` → `Completed` (or `Needs attention`) |
| Last updated (UTC) | time of the last change |
| Notes | error details, if any |

Add a data-validation dropdown on **Status** with those values, and
conditional formatting: `Completed` green, `Needs attention` red,
`Not a creator yet` grey.

---

## Before turning it on

- The bot that posts must have **Manage Channels** in category
  `1557840609664958599` and **Manage Roles** on the server, and its role must
  sit **above** both `1534216662415573023` and `1559649034598227968` in Server
  Settings → Roles.
- Discord allows at most 50 channels in one category. Moderators delete
  finished onboarding channels by hand (there is no 🔒 Close button any more).
- Test the whole flow with a test account before turning on Zap 1.
