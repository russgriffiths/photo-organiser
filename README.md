# Photo Organiser

Moves photos from a NAS `Inbox` (and its subfolders) into `Organised/YYYY/MM/DD` by
capture date, with a dry-run preview, duplicate detection, an audit trail and undo.
The folder depth (year, month or day) and the order of date sources are settings.
Runs as a Home Assistant app (Pi with Home Assistant OS, NAS share mounted by Home
Assistant), or as a plain Docker container against a Synology share over NFS.

Design: [Photo Organiser — Architecture Design](https://claude.ai/artifact/Tmq19dDYn9MbvkzH58u4pf)

## Layout

```text
app/
  config.py         environment settings (paths, secret key)
  models/           runs, move_history, file_index, settings
  services/
    scanner.py      walks Inbox, groups photo + companions (MOV, AAE, XMP, RAW+JPEG)
    metadata.py     ExifTool reader + date rules
    planner.py      decides move / duplicate / reject / skip; touches no files
    mover.py        applies a plan; the only code that moves files in
    undo.py         moves a run's files back
    index.py        file_index cache of the library, hashes on demand
    history.py      writes plans to move_history, reloads a dry run's plan
  jobs/
    runner.py       one run at a time, in a background thread
    scheduler.py    daily organise, weekly index, Inbox count every 15 min
  routes/           one blueprint per page
tests/              pytest; uses a fake metadata reader, no ExifTool needed
```

## Install as a Home Assistant app

This folder is also a Home Assistant app (`config.yaml`; Home Assistant called these
add-ons before 2026.2), which is how it runs on a Pi with Home Assistant OS. The UI
opens in the Home Assistant sidebar and Home Assistant handles the login, so the
app's own password is switched off.

1. In Home Assistant, add the Synology share under **Settings → System → Storage →
   Add network storage**: name `Photos`, usage **Media**, protocol **CIFS**, signing
   in as the `photo-organiser` NAS user. It appears to apps at `/media/Photos`.
2. Copy this folder to `/addons/photo-organiser`, leaving out `.git`, `data/`,
   `test-photos/` and `test-data/`. Either:
   - **Studio Code Server** app: open folder `/addons`, create `photo-organiser`,
     drag the files in from Windows Explorer; or
   - **Terminal & SSH** app (SSH port enabled), from Git Bash in this folder:

     ```bash
     git archive HEAD | ssh root@homeassistant.local "rm -rf /addons/photo-organiser && mkdir -p /addons/photo-organiser && tar -xf - -C /addons/photo-organiser"
     ```

3. **Settings → Apps → Install app → ⋮ → Check for updates**. Photo Organiser
   appears under **Local apps**. Install it; Home Assistant builds the image on
   the Pi, which takes a few minutes the first time.
4. On the **Configuration** tab, set `photos_path` (default `/media/Photos`). For a
   first test, use a folder of copied photos under `/share`, e.g. `/share/photo-test`
   containing `Inbox` and `Organised`.
5. Start it, tick **Show in sidebar**, and open **Photos**.

To update after changing the code, bump `version` in `config.yaml`, copy the folder
again, then use **Rebuild** on the app's page.

## Deploy with Docker Compose (without Home Assistant)

1. On the Synology:
   - Create a user `photo-organiser` with read/write on the `Photos` shared folder.
   - Create `Inbox`, `Organised`, `Duplicates` and `Rejected` inside it.
   - Enable NFS and add an NFS rule on `Photos` for the Pi's IP only.
   - Note the user's UID and GID (for example via SSH: `id photo-organiser`).
2. In `docker-compose.yml`, set `user:` to that UID:GID, and set `addr=` and `device:`
   to the NAS address and export path.
3. On the Pi:

   ```bash
   mkdir -p data && sudo chown 1030:100 data   # same UID:GID as above
   docker compose up -d --build
   ```

4. Open `http://raspberrypi.local:5000`, set the password, then press
   **Index library now** before the first dry run.

The container refuses to start if `/photos/Inbox` or `/photos/Organised` is missing,
which usually means the NFS mount failed.

## First use

1. Index the library (Dashboard or Settings). This only lists files; contents are
   hashed later, and only when two files have the same size.
2. Press **Dry Run** and check the Preview page, especially the `reject`, `duplicate`
   and `renamed` filters.
3. Press **Organise**. Within 24 hours of a dry run it applies exactly the previewed
   plan, re-checking each file first.
4. Keep the daily schedule off (Settings) until a few manual runs look right.

Test against a copy of a few hundred photos before pointing it at the real library.

## Test run with sample photos

Before connecting the NAS, run the container on the Pi (or any Docker host)
against a local folder of copied photos. ExifTool is inside the image, so nothing
else needs installing.

1. Copy 50–100 photos into a test Inbox. Include a mix: iPhone HEIC with Live
   Photo MOVs, Android JPEGs, a few RAW files, WhatsApp images, screenshots.
   Always copy, never move, from your real library.

   ```bash
   mkdir -p test-photos/Inbox test-photos/Organised test-data
   cp -r /path/to/sample/photos/. test-photos/Inbox/
   ```

2. Start it with the test override, which swaps the NFS volume for `./test-photos`:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build
   ```

3. Open `http://raspberrypi.local:5000`, set a password, then:
   - **Dry Run**, and check the Preview: dates, `reject`, `duplicate`, `renamed`.
   - **Organise**, and look at `test-photos/Organised`.
   - **Undo Last Run**, and check everything is back in `test-photos/Inbox`.
   - Organise again with a few copies of the same photo in the Inbox to see
     duplicate handling.

4. To start again: `docker compose -f docker-compose.yml -f docker-compose.test.yml down`
   and delete `test-photos` and `test-data`.

Files waiting less than 5 minutes are skipped (they might still be copying), so
wait 5 minutes after copying, or set the wait to 0 in Settings.

## Develop and test

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use a fake metadata reader, so ExifTool isn't needed to run them.
Running the app outside Docker needs ExifTool on the `PATH`, and `PHOTOS_ROOT` and
`DATA_DIR` set to local folders.

## Environment variables

| Variable | Default | |
| --- | --- | --- |
| `PHOTOS_ROOT` | `/photos` | NAS mount |
| `DATA_DIR` | `/data` | database, logs, secret key |
| `INBOX_DIR`, `ORGANISED_DIR`, `DUPLICATES_DIR`, `REJECTED_DIR` | `Inbox` … | folder names under `PHOTOS_ROOT` |
| `SECRET_KEY` | generated once into `/data/secret_key` | session signing |
| `TZ` | | set to your timezone so the 02:00 schedule is local |

## Backup

Back up `data/database.db` (it holds the history that undo needs). Use
`sqlite3 data/database.db ".backup data/backups/db-$(date +%F).db"` from cron, and
include `data/` in Hyper Backup. `file_index` can always be rebuilt with an index run.
