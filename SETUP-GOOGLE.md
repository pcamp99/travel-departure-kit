# Giving the tool access to your calendar

Only needed for `fix_timezones.py` and the `--add-to-calendar` flag.
`plan_departure.py` works without any of this.

This is free. Google calls it a "Cloud project" but you are not deploying
anything or paying anything; it is just how they issue credentials for a
script that talks to your own account.

Roughly ten minutes, once.

## 1. Make a project

Go to <https://console.cloud.google.com/projectcreate>. Name it anything.
Create.

**Done when:** the project name appears in the picker at the top of the page.

## 2. Turn on the Calendar API

In the search bar at the top, type "Google Calendar API", open it, and press
**Enable**.

**Done when:** the button changes to "Manage".

## 3. Set up the consent screen

Left menu, **APIs & Services > OAuth consent screen**. Choose **External**.
Fill in an app name and your own email in the two contact fields. Save through
the remaining pages; you can leave scopes empty.

Then find **Audience** in the left menu and add your own Google address under
**Test users**.

**Done when:** your email appears in the test users list.

> This step is the one that bites people. If you skip the test user, the sign
> in later fails with "app is blocked" or "has not completed verification",
> which reads like the app is broken rather than like a setting you missed.

## 4. Create the credential

**APIs & Services > Credentials > Create credentials > OAuth client ID**.
Application type: **Desktop app**. Create, then **Download JSON**.

Rename the downloaded file to `credentials.json` and put it in the repo folder
next to `plan_departure.py`.

**Done when:** `credentials.json` sits in the repo root. It is already
gitignored.

## 5. First run

```bash
python3 fix_timezones.py --days 90
```

A browser opens asking you to sign in and approve. Approve it. You will see an
"unverified app" warning; that is expected for a script you built yourself, and
you get past it via **Advanced > Go to (your app name)**.

**Done when:** the terminal prints either a list of findings or
`Checked N events. Nothing looks wrong.`

A file called `token.json` now exists. **That file is a live credential for
your calendar.** It is gitignored. Do not email it, do not paste it, and if
you ever think it leaked, revoke it at
<https://myaccount.google.com/permissions>.

## If it goes wrong

**"Access blocked: app has not completed verification"** — you are signing in
with an account that is not in the test users list from step 3. Add it, or sign
in with the account you did add.

**"No credentials.json"** — the download landed in Downloads with a long
generated name. Rename it to exactly `credentials.json` and move it to the repo
root.

**The browser opens and hangs** — the script starts a local server for the
callback. A VPN or a locked down corporate machine can block it. Try on a
personal network first.

**It runs but finds nothing on a calendar you know has problems** — check
`--days`. The default only looks 90 days ahead.
