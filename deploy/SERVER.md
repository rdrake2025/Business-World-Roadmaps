# Moving AnswerRank onto its own server

**Why you need this:** every email you send has an unsubscribe link, and the
law and the mailbox providers both require that link to work — from anywhere,
all the time. Right now the app runs on your laptop, reachable only on your
home Wi-Fi, and it stops whenever the laptop sleeps. The doctor will not let
you send a single email until the link works publicly.

A small server fixes that, and makes "runs 24/7" literally true. It costs
about **$6 a month**. You will not need to type any commands on it.

---

## Before you start

- Your keys are saved (AnswerRank button → **Keys and settings**, if you haven't).
- You know your domain, e.g. `getanswerrank.com`.
- You can log in to wherever you bought the domain (the "registrar").

## 1. Make the setup file (on your laptop, 1 minute)

AnswerRank button → **5 Make the server setup file**. Press Enter to use the
domain you send from.

It writes a file called `server-setup-getanswerrank.com.sh`, opens it in
Notepad, and prints your
**console link** — the address you'll use on your phone from now on.
**Save that link somewhere safe; it is your login.**

The setup file contains your keys. Don't email it or share it, and delete it
once the server is running.

## 2. Create the server (5 minutes)

**DigitalOcean** (recommended — simplest screens, US data centres):

1. Sign up at digitalocean.com and click **Create → Droplets**.
2. Region: the one nearest you. Image: **Ubuntu 24.04 (LTS)**.
3. Size: **Basic → Regular → $6/month** (1 GB). That is plenty.
4. Authentication: choose **Password** and set a strong one (you won't need
   it day to day, but you'll want it for emergencies).
5. Open **Advanced Options** and tick **Add Initialization scripts (free)**.
   A **User data** box appears.
6. Open your `server-setup-….sh` file in Notepad, select everything, copy,
   and paste it into that box.
7. Click **Create Droplet**. Note the **IP address** it shows (four numbers
   separated by dots).

**Hetzner** works the same way and is a little cheaper: when creating a
server, paste the file into the **Cloud config** box.

## 3. Point your domain at the server (5 minutes)

At your registrar's DNS settings, add (or change) one record:

| Type | Name | Value |
| --- | --- | --- |
| A | `@` | the server's IP address |

Leave your email records (SPF, DKIM, DMARC, MX) exactly as they are — this
record is only for the website.

## 4. Check it (after about 10 minutes)

The server installs itself, then gets its HTTPS certificate once your domain
points at it. DNS can take anywhere from a few minutes to an hour.

On your laptop, run the doctor. When **Unsubscribe endpoint** shows ✓, you're
live. Then open your console link on your phone and add it to your home screen.

## From now on

- **The server runs the agents.** The AnswerRank button's **Open AnswerRank**
  notices and opens your server's console instead of starting a second copy
  on the laptop (two copies would send every email twice). On your phone, use
  the console link.
- **Updates are automatic.** Every night at 4:30 the server pulls the latest
  version, the same way the AnswerRank button does on the laptop.
- **Backups are automatic.** The database is backed up every night at 3:00 and
  kept for 30 days, on the server.
- **Keys:** to change one, use Keys and settings on the laptop, make a new setup file,
  and ask for help applying it — or change it on the server with the
  provider's web console.

## If something goes wrong

The server writes everything it did to `/var/log/answerrank-setup.log`. In
DigitalOcean, open the droplet, click **Access → Launch Droplet Console**, and
type `tail -50 /var/log/answerrank-setup.log` to see the end of it.
