# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a personal photo library managed by **Adobe Lightroom Classic v13.4**, not a software development project. There are no build systems, scripts, or source code.

## Key Files

- **`Lightroom Catalog-v13-4.lrcat`** — Main catalog (SQLite 3.x database, ~1.1GB). Contains all photo metadata, collections, keywords, ratings, flags, and edit history.
- **`Lightroom Catalog-v13-4 Previews.lrdata/`** — Rendered preview cache.
- **`Lightroom Catalog-v13-4 Smart Previews.lrdata/`** — Compact DNG previews for offline editing.
- **`Backups/`** — Lightroom-generated catalog backups.
- **`Old Lightroom Catalogs/`** — Archive of previous catalog versions.

## Photo Organization

Photos are organized chronologically and by category:

- **`1904/`, `1999/`, `2000s/`, `2010s/`, `2020s/`, `2026/`** — Year/decade folders.
- **`SLR/`** — DSLR camera photos.
- **`scans/`** — Digitized physical photos.
- **`cleanup folders/`** — Per-year (2009–2022) folders used during de-duplication work.
- **`photos-sort-archive/`** — Large unsorted archive (~1.3GB).
- **`client folders/`**, **`etsy shop/`**, **`instagram sync/`** — Category-specific collections.

## Working with the Catalog

The `.lrcat` file is a SQLite database and can be queried directly, but **do not write to it while Lightroom is open or at all - if you need to ask the user before continuing** — concurrent writes will corrupt the catalog. Always work on a backup copy for any exploratory queries.

## Project Scope

# Photo Evaluation System
## Claude Code + Full Dropbox Database

### Overview

A persistent, scriptable system for evaluating photos across the entire Dropbox archive. Designed to work across multiple sessions, trips, years, and evaluation purposes (Etsy, Instagram, portfolio). The database is the single source of truth for what's been reviewed, what hasn't, and what the verdicts were.

---

### Database Root Example

```
D:\Dropbox\mac photos\
├── 2020s\
│   ├── 2022\MM\DD\
│   ├── 2023\MM\DD\
│   ├── 2024\MM\DD\
│   └── 2025\MM\DD\
├── (earlier decades if they exist)
└── ...
```

File naming: Nikon Z6ii files use `Z62_` prefix. Older/iPhone files use `IMG_` prefix.

---

### Database Schema

```sql
-- Core photo inventory
CREATE TABLE photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    folder_path TEXT NOT NULL,          -- relative to database root, e.g. "2020s/2025/04/13"
    extension TEXT,                      -- NEF, JPG, etc.
    file_size INTEGER,                   -- bytes, useful for spotting anomalies
    camera_prefix TEXT,                  -- Z62_, IMG_, etc.
    date_taken TEXT,                      -- from folder structure: YYYY-MM-DD
    is_personal BOOLEAN DEFAULT 0,       -- in a "personal" subfolder, auto-skipped
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(folder_path, filename)
);

-- Evaluation results (one photo can be evaluated for multiple purposes)
CREATE TABLE evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL,
    eval_type TEXT NOT NULL,              -- 'etsy', 'instagram', 'portfolio'
    verdict TEXT,                         -- 'yes', 'edge_case', 'no'
    rationale TEXT,                       -- 1-2 lines for yes, paragraph for edge
    rejection_reason TEXT,               -- category for no (e.g. "tourist snapshot", "technical failure")
    paper_recommendation TEXT,           -- Etsy only: Pearl, Baryta, Photo Rag, etc.
    batch_id INTEGER,                    -- links to evaluation_batches
    reviewed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (photo_id) REFERENCES photos(id),
    FOREIGN KEY (batch_id) REFERENCES evaluation_batches(id)
);

-- Batch/session tracking
CREATE TABLE evaluation_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_type TEXT NOT NULL,
    target_folder TEXT,                  -- what folder range was being evaluated
    session_date TEXT DEFAULT (date('now')),
    images_reviewed INTEGER DEFAULT 0,
    notes TEXT
);

-- Etsy listing pipeline (for photos that pass evaluation)
CREATE TABLE etsy_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL,
    title TEXT,
    description TEXT,
    tags TEXT,                            -- comma-separated, max 13, each ≤20 chars
    paper TEXT,
    status TEXT DEFAULT 'draft',          -- draft | listed | sold
    listed_date TEXT,
    collection TEXT,                      -- e.g. "Venice", "Miami Art Deco"
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (photo_id) REFERENCES photos(id)
);

-- Scan tracking (know what's been indexed vs. not)
CREATE TABLE folder_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT NOT NULL UNIQUE,
    file_count INTEGER,
    personal_count INTEGER DEFAULT 0,     -- files in personal subfolders
    scanned_at TEXT DEFAULT (datetime('now')),
    last_evaluated TEXT,                   -- when evaluation was last run on this folder
    eval_type_last TEXT                    -- what type of evaluation was last run
);
```

---

### Workflow

#### 1. Scan (run once per folder, re-run to pick up new files)

```
scan [folder_path]           -- e.g. "2020s/2025/04" scans all subfolders
scan --year 2025             -- scans everything under 2025
scan --all                   -- indexes the entire database (first run will be slow)
```

The scan script:
- Walks the folder tree recursively
- Inserts every photo file (NEF, JPG, TIFF, etc.) into the `photos` table
- Marks files in `personal` subfolders as `is_personal = 1`
- Updates `folder_scans` with counts
- Is idempotent: re-running updates counts and adds new files without duplicating

#### 2. Evaluate

```
evaluate [folder_path] --type etsy       -- evaluate for Etsy
evaluate [folder_path] --type instagram  -- evaluate for Instagram
evaluate --trip "Venice Rome April 2025" -- evaluate by trip label
evaluate --pending --type etsy           -- pick up where you left off
```

The evaluate command:
- Queries for photos where no evaluation exists for the given type
- Generates/extracts JPEG previews (embedded JPEG from NEF via exiftool)
- Batches 10-15 images at a time for viewing
- After each batch, updates the database with verdicts
- Creates an evaluation_batch record per session

#### 3. Report

```
report --type etsy                       -- summary of all Etsy evaluations
report --folder "2020s/2025/04"          -- stats for a specific trip
report --pending                         -- what hasn't been reviewed yet
report --yes --type etsy                 -- list all Etsy-worthy images
```

#### 4. Listing (Etsy pipeline)

```
listing [photo_id]                       -- generate title/description/tags for one image
listing --queue                          -- work through all yes-verdict images without listings
listing --collection "Venice"            -- generate listings for a collection
```

---

### JPEG Preview Strategy

NEF files can't be viewed directly. Extract the embedded camera JPEG:

```bash
# Single file
exiftool -b -JpgFromRaw -w _preview.jpg input.NEF

# Batch: generate previews for all NEFs in a folder
exiftool -b -JpgFromRaw -w _preview.jpg -r "D:\Dropbox\mac photos\2020s\2025\04\"
```

Previews go alongside originals or into a `.previews` subfolder. Sufficient quality for curation. Full raw processing happens in Lightroom after curation.

---

### Evaluation Criteria

#### Etsy (Fine Art)
- Location-independent, emotionally resonant, no tourist cliches
- People OK if face mostly/fully obscured, street photography legal context
- Branding OK unless it dominates. Flag but check for irony/juxtaposition/context
- Visible addresses are fine
- Don't harshly judge exposure/WB/colour: all files are unedited
- Paper recommendation required: Pearl (vibrant colour), Baryta (architectural/industrial), Photo Rag (default), German Etching (vintage/textured), Bamboo, Ilford Cotton Textured, Epson Semi-Gloss
- Non-traditional fine art is in scope

#### Instagram
- Broader selection: documentary, observational, street photography all valid
- Looser identifiability threshold: full face OK for street/portrait context
- Tattoos, uniforms treated loosely with contextual judgment
- Engagement potential matters alongside artistic merit

#### Portfolio
- Draw from both Etsy and Instagram criteria
- Strongest work regardless of commercial viability

### Output Format
- **YES:** filename + 1-2 line rationale (+ paper recommendation for Etsy)
- **EDGE CASES:** filename + detailed paragraph on tensions
- **NO:** grouped by rejection reason

---

### Session Startup Checklist

For any new Claude Code session working with this system:

1. Check database exists. If not, create it
2. Run `report --pending` to see what needs doing
3. Confirm exiftool is available
4. Pick up evaluation from where last session left off (query evaluation_batches for last reviewed folder/file)

---

### First Run: Venice & Rome (April 13-18, 2025)

Priority evaluation target. Steps:
1. `scan 2020s/2025/04` — index all April 2025 subfolders (13-18)
2. Review folder_scans for file counts
3. `evaluate 2020s/2025/04 --type etsy` — begin Etsy evaluation
4. Complete one date folder before moving to next (keeps location context coherent)

---

### Future Expansion Ideas

- **Trip labels table:** map folder ranges to trip names ("Venice & Rome", "Miami 2024", etc.)
- **Series detection:** flag consecutive file numbers that might be burst sequences
- **Duplicate detection:** hash-based matching across folders
- **Export to Lightroom:** generate a text file of selected filenames for Lightroom import filtering
- **Analytics:** hit rates by trip, by year, by camera. Which trips yield the most Etsy-worthy shots?

