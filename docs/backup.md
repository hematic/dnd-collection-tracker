# Back up and restore

← [Back to the README](../README.md) · [Docker hosting](docker.md)

A backup of `/data` includes the database, covers, ownership, notes, PDF links, and search index. **CSV export is an inventory, not a backup.** Back up the PDF library and any `.env` file separately. Keep the archives somewhere private and off the tracker host.

Run these commands from the Compose folder in a POSIX shell. Stop both the app and its OCR worker before archiving the data so neither can write to SQLite during the backup.

## Local-only setup (Docker volume)

```sh
backup_dir=$(mktemp -d "$HOME/dnd-tracker-backup.XXXXXXXX") &&
  docker compose -f compose.local.yml stop &&
  docker compose -f compose.local.yml run --rm --no-deps -T --entrypoint tar dnd-tracker \
    -C /data -czf - . > "$backup_dir/tracker-data.tar.gz" &&
  tar -tzf "$backup_dir/tracker-data.tar.gz" &&
  docker compose -f compose.local.yml up -d &&
  printf 'Backup saved to %s\n' "$backup_dir"
```

To restore, replace `backup_file` below with the archive's absolute path. Choose an **unused** Compose project name so its volume is empty. Keep the same PDF mount and, for rollback, pin the same image version that produced the backup before running these commands. The old volume is left untouched.

```sh
backup_file=/absolute/path/to/tracker-data.tar.gz
docker compose -f compose.local.yml stop &&
  docker compose -p dnd-tracker-restored -f compose.local.yml \
    run --rm --no-deps -T --entrypoint tar dnd-tracker \
    -C /data -xzf - < "$backup_file" &&
  docker compose -p dnd-tracker-restored -f compose.local.yml up -d
```

Verify the restored collection before removing any old data. If you keep the restored instance, include `-p dnd-tracker-restored` in future Compose commands.

## Authenticated setup (data folder)

Replace `data_dir` with the `DND_DATA_DIR` value in your `.env`. Run as a user that can read the entire data directory, including the database.

```sh
data_dir=/absolute/path/to/tracker-data
backup_dir=$(mktemp -d "$HOME/dnd-tracker-backup.XXXXXXXX") &&
  docker compose stop &&
  tar -C "$data_dir" -czf "$backup_dir/tracker-data.tar.gz" . &&
  tar -tzf "$backup_dir/tracker-data.tar.gz" &&
  docker compose up -d &&
  printf 'Backup saved to %s\n' "$backup_dir"
```

To restore, stop the stack and extract into a **new, empty** data directory. Leave the old directory untouched until you've verified the restore.

```sh
backup_file=/absolute/path/to/tracker-data.tar.gz
restored_dir=/absolute/path/to/new-tracker-data
docker compose stop &&
  mkdir "$restored_dir" &&
  tar -C "$restored_dir" -xzf "$backup_file"
```

Give the configured `PUID:PGID` ownership of the restored directory and its contents, set `DND_DATA_DIR` in `.env` to that directory, and use the original PDF mount and path mapping. For rollback, pin the image version that produced the backup. Then run `docker compose up -d` and verify the collection. If a backup or restore command fails, resolve the error before using the archive or starting the restored stack.
