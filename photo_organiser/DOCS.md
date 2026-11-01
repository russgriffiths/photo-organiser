# Photo Organiser

Moves photos from an `Inbox` folder, including all its subfolders, into date
folders under `Organised`. Every run can be previewed first, every move is
recorded, and any run can be undone.

## Setup

1. Add the NAS share under **Settings → System → Storage → Add network storage**:
   - Name `Photos`, usage **Media**, protocol **Samba/Windows (CIFS)**.
   - Sign in as a NAS user with read/write on that share only.
2. On the share, create `Inbox` and `Organised`. `Duplicates` and `Rejected` are created
   automatically.
3. Set **photos_path** on the Configuration tab if the share isn't at `/media/Photos`.
   Folders under `/share` work too, which is handy for a first test.
4. Start the app and open **Photos** in the sidebar.
5. Press **Index library now** before the first dry run, so photos already in
   `Organised` are recognised as duplicates.

The app won't start if `Inbox` or `Organised` is missing under `photos_path`;
the Log tab says which. That usually means the network storage isn't connected.

## Using it

- **Dry Run** works out every move without touching a file. Check the Preview,
  especially the `reject`, `duplicate` and `renamed` filters.
- **Organise** applies the latest preview if it's under 24 hours old, re-checking
  each file first. Otherwise it scans the Inbox and organises in one go.
- **Undo Last Run** moves that run's files back. A file is skipped if it was changed
  or moved since.
- The daily schedule (02:00 by default) starts switched off. Switch it on in
  Settings once a few manual runs look right.

## Settings page

- **Folder structure**: year (`Organised/2025/`), month (`Organised/2025/07/`) or
  day (`Organised/2025/07/04/`, the default). A change applies to photos organised
  afterwards; photos already in `Organised` aren't moved.
- **Finding the date**: the ways the app looks for a photo's date, tried from the
  top down, and the first valid date wins. Tick or untick each one and move it up or
  down. The choices are the EXIF date taken, date created and date digitised, a date
  in the file name, and the file's modified date. The modified date is off by
  default because copying a file resets it; dates from it are marked "low
  confidence" in the Preview.
- **Duplicates**: move exact copies to `Duplicates`, or leave them in the Inbox.
- **Wait before picking up new files**: files changed more recently than this are
  left for the next run, in case they're still copying.

## Data and backups

The history that undo relies on is stored in the app's own data folder, which
Home Assistant backups include. Photos aren't in the backup; they stay on the NAS.
