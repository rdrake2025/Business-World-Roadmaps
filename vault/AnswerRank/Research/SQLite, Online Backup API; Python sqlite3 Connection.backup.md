---
tags: [answerrank, research]
published: 2026
checked: 2026-09
---
# SQLite, Online Backup API; Python sqlite3 Connection.backup

[Read the source](https://www.sqlite.org/c3ref/backup_finish.html)

## What it found
The online backup API copies a database that is in use into a consistent snapshot; copying the file directly can capture a half-written state.

## So AnswerRank
Backups use Connection.backup, never a file copy, and are compressed before they leave the server.

Used by: `backup`. Read again every 24 months.

Part of [[Research]].
