# Changelog

User-visible changes are recorded here using MAJOR.MINOR.PATCH version numbers.

## [0.39.2] - 2026-11-19

### Added
- Publish versioned Docker Hub images for Linux amd64 and arm64, with matching GitHub releases.
- Let both Compose services pull the same prebuilt image and set their host UID and GID without rebuilding.

## [0.39.1] - 2026-11-19

### Changed
- Redesign the PDF library picker with breadcrumb navigation, keyboard-friendly rows, and a layout that fits narrow screens.

## [0.39.0] - 2026-11-19

### Changed
- Browse the configured PDF library and link releases using portable library-relative paths. Existing pasted paths still work.

## [0.38.1] - 2026-11-19

### Changed
- Make legacy Windows and NAS PDF path mappings optional and configurable in Docker Compose.

## [0.38.0] - 2026-11-19

### Removed
- Retire all one-off catalog comparison, diagnostic export, identity-mapping, metadata repair and verified-copy consolidation tools, including their UI, APIs, code, proposal manifests and Docker packaging.
- Remove obsolete catalog-review instructions and tool-only tests from the public app.

### Preserved
- Keep the full 1,048-work / 1,115-release fresh catalog, normal collection editing, indexing and exports.
- Retain existing catalog mappings, repair audits, deletion markers, old-work redirects, backups and startup preservation gates. No pending repair is applied automatically.

## [0.37.0] - 2026-11-19

### Added
- Add explicit PDF-fingerprint-verified S1/C1 printing repairs and Greyhawk booklet date corrections, with full backups, stale-preview guards, preservation checks and non-replaying audits.
- Offer separately confirmed C1 consolidation into one work with two preserved releases, an archived source work and a read-only redirect for its old bookmark.

### Changed
- Preserve existing bibliography during the reviewed rollout; add release-level reconciliation gates so new cover-family identities cannot duplicate existing copies on startup.
- Separate unknown printing years from original publication years and recognize explicitly documented, corroborated unknown-year alternate covers without guessing dates.
- Fresh instances receive 1,048 works and 1,115 releases, including both reviewed S1/C1 cover families and corrected 1983 Greyhawk booklet dates.

## [0.36.0] - 2026-11-19

### Changed
- Seed the complete reviewed catalog only into verified empty collections; preserve existing-collection reconciliation gates, mappings and deletions.
- Count conflicts on canonical or mapped identities as needing review and recognize compound stock-number suffixes without equating printings.
- Offer four explicitly reviewed, backup-backed Greyhawk/Forgotten Realms component parent-link repairs while preserving all release and private data.

## [0.35.0] - 2026-11-18

### Changed
- Distinguish corroborated catalog editions, printings and boxed-set components in the read-only comparison while retaining all matching evidence and genuine duplicate warnings.
- Resolve twelve documented comparison collisions without changing collection data, catalog identities, mappings, assets or approval history; retain High-Level Campaigns for explicit duplicate review.

## [0.34.0] - 2026-11-18

### Changed
- Add four copy-reviewed proposals separating original work years from verified reprints, preserving unresolved copy dates and all earlier approvals.
- Add two gated reprint identities with exact kind/year/stock/ISBN checks and separate backup-backed mapping confirmation; preserve local IDs, assets, private data and fresh-install gates.

## [0.33.0] - 2026-11-18

### Changed
- Add two source-verified ISBN-only proposals for WG9 Gargoyle and WGQ1 Patriots of Ulek, with exact mapped/unmapped counterpart guards and explicit backup-backed approval.
- Publish the corrected original-release ISBNs without changing catalog coverage, stable IDs, prior repair proposals, identity mappings, or startup bibliography; retain all copy-specific holds.

## [0.32.0] - 2026-11-18

### Changed
- Review the final 21 official catalog holds together; add six gated, source-backed identities while retaining 15 unresolved identity holds and the 70 personal third-party exclusions.
- Add five exact prerequisite repairs plus a work-only D&D Companions classification for The Worlds of TSR without changing its disputed printing or offering an unverified mapping.
- Distinguish L3 booklet stock 9844 from collector-set stock 11549, use photographed edition branding and publisher publication histories, and preserve all previous approvals, local IDs and fresh-install gates.

## [0.31.0] - 2026-11-18

### Changed
- Add a dedicated D&D Companions shelf, with separate filtering, editing, bookmarks and collapse state, positioned after RPG editions and before unchanged Other.
- Keep the ten reviewed companion identities stable and add exact, backup-backed edition-only follow-ups for pending or already-mapped records; preserve all 113 prior proposals and audit history.
- Leave unrelated Other and third-party books untouched, preserve fresh-install gates, and require explicit prerequisite approvals without automatic startup moves.

## [0.30.0] - 2026-11-18

### Changed
- Add ten gated official TSR companion identities and exact work-only classification proposals from an eleven-case review; retain The Worlds of TSR as an ISBN-specific printing hold.
- Use the existing Other edition for independent art, atlas, history, gamebook and game products with strict source-backed complete-product confirmation; preserve functional types and all release metadata.
- Preserve all previous approvals, personal exclusions and fresh-install gates; keep the 100-item transaction limit for the cumulative 113 repair proposals.

## [0.29.0] - 2026-11-18

### Changed
- Add five gated complete-product identities from an eleven-case bundle/component review, with five separate exact metadata proposals and six unresolved holds.
- Add narrow Basic accessory-title and legacy fourth-edition kit repair profiles; admit explicitly confirmed original Wizards 4e boxes without relaxing historical scopes or component guards.
- Preserve all previous identities, personal exclusions, and fresh-install gates; verify cumulative repairs and mappings in separate transactions of at most 100.

## [0.28.0] - 2026-11-18

### Changed
- Add sixteen gated identities from a consolidated thirty-record metadata review, with ten exact repair proposals and fourteen unresolved holds.
- Disambiguate original adventures, compilations, and historical screens with reviewed titles; preserve separate identities and strict matching.
- Add narrow stock-code accessory and 1983 Basic RPGA repair profiles, retain TSR imprints and supported local publication years, and preserve all previous approvals and personal exclusions.

## [0.27.0] - 2026-11-18

### Changed
- Add nineteen gated complete-product identities from a twenty-two-product official accessory review, with nine separate exact metadata proposals and three unresolved holds.
- Require a strict complete-product confirmation without forcing functional book types into Boxed Set; preserve existing whole-box confirmations and reject component relationships.
- Add a classification-only Basic accessory repair profile while retaining all existing repair permissions, personal exclusions, file links, and fresh-install gates.

## [0.26.0] - 2026-11-18

### Changed
- Add five source-verified TSR whole-box identities using the existing separately confirmed, backup-backed mapping workflow, taking approvals from 532 to 537 without metadata repairs.
- Resolve the remaining original-publisher source gaps for the five boxes; preserve all prior catalog entries, repair proposals, local records, files, and fresh-install gates.
- Clarify that personal third-party additions and their product families stay local-only and are outside the shared/default catalog expansion backlog.

## [0.25.0] - 2026-11-18

### Changed
- Consolidate the remaining 183-record review into 37 gated identities: 33 whole boxed products, Hero Builder's Guidebook, and three repair-first standalone products.
- Add opt-in edition-only correction for In the Phantom's Wake, title-only Elixer-to-Elixir correction for RPGA4, and title/missing-year correction for GR4 Treasure Chest while preserving its exact ISBN.
- Require a separate, strict whole-box confirmation in the UI and API; reject boxes with existing component relationships and leave PDF completeness unverified.
- Restrict the new Basic adventure profile to AD&D 1e-to-Basic edition changes while preserving all release metadata and existing repair permissions.
- Document one three-repair transaction followed by one 37-mapping transaction, taking 495 mappings to 532; keep the other 146 records held without inventing identifiers, merging components, renaming files, or changing links.

## [0.24.0] - 2026-11-18

### Changed
- Add four gated catalog identities for Into the Dragon's Lair, Servants of Darkness, The Shadow Rift, and The Wyrmskull Throne using their separately reviewed metadata corrections.
- Enable a mapping-only 491-to-495 approval batch without new metadata repairs, filename changes, merges, or changes to existing repair permissions.
- Preserve skipped-upgrade repair prerequisites and fresh-install gates; document the separate backup-backed mapping approval.

## [0.23.0] - 2026-11-18

### Changed
- Add eighteen explicitly approved AD&D title-only repairs and twenty gated catalog identities, keeping the two Greyhawk titles unchanged.
- Add an isolated title-only selector and narrowly validate formatted stock-code prerequisites without changing release metadata, filenames, prior mappings, or deferred proposals.
- Document the separate backup-backed title repair and catalog mapping workflow, taking approved mappings from 471 to 491.

## [0.22.0] - 2026-11-18

### Changed
- Add fifteen gated AD&D second-edition catalog mappings for previously repaired adventures, supplements, and trail maps without changing local metadata or files.
- Preserve all earlier mappings and repair history, keep deferred records excluded, and support repair-then-mapping upgrades with exact prerequisite metadata.

## [0.21.0] - 2026-11-18

### Changed
- Add gated identities for the 1981 Moldvay Basic Rulebook and the 1987 In Search of Adventure compilation, with a separate exact-before-value year repair.
- Expose thirteen OD&D/Basic holds as read-only PDF reviews and provide independent Basic-only and standalone-PDF repair selectors without selecting deferred repairs.

## [0.20.0] - 2026-11-18

### Changed
- Add three official fifth-edition standalone PDF identities with explicitly namespaced DMs Guild identifiers, exact source checks, and separate opt-in identifier repair and catalog mapping approvals.
- Add PDF-only repair selection so deferred AD&D proposals stay unchecked; preserve titles, filenames, links, private collection data, indexes, and all prior approvals.

## [0.19.0] - 2026-11-18

### Changed
- Add nineteen opt-in AD&D 2e metadata proposals with exact before-value guards and a separate narrowly validated repair profile; preserve the original thirty-five repairs and all catalog mappings.
- Prioritize pending metadata reviews, collapse completed history, and provide direct linked-PDF inspection before explicit backup-backed approval.

## [0.18.0] - 2026-11-18

### Changed
- Add forty-six reviewed AD&D 2e whole-product identities to both reconciliation-gated catalogs, preserving all 405 prior entries and the 100-entry approval limit.
- Keep the 19 repair-first records and 84 review holds separate; preserve local book/release data, repair history, files, and indexes through backup-backed mapping approval.

## [0.17.0] - 2026-11-18

### Changed
- Add seventeen reviewed AD&D 1e whole-product identities to both reconciliation-gated catalogs, preserving all 388 prior entries and the 100-entry approval limit.
- Keep the five proposed metadata corrections and 25 review holds separate; preserve local book/release data, repair history, files, and indexes through backup-backed mapping approval.

## [0.16.1] - 2026-11-17

### Changed
- Show ready catalog mappings first, keep blocked entries visible, and collapse completed mapping history by default.

## [0.16.0] - 2026-11-17

### Changed
- Add eleven reviewed Basic D&D whole-product identities to both reconciliation-gated catalogs, preserving all 377 prior entries and the 100-entry approval limit.

## [0.15.0] - 2026-11-17

### Changed
- Add 35 reviewed, reconciliation-gated third-edition catalog entries, correctly recognize verified Paizo product numbers, and preserve the prerequisite metadata-repair workflow for skipped-version upgrades.

## [0.14.0] - 2026-11-17

### Changed
- Add opt-in, backup-backed third-edition metadata repairs with exact before-value checks, admin review, persistent repair history, and preservation of IDs, files, personal data, and catalog mappings.

## [0.13.0] - 2026-11-17

### Changed
- Add eight verified remaining Basic D&D and AD&D 2e entries to the gated reconciliation catalog, preserving all 334 prior entries
- Keep strict metadata checks and the 100-entry transaction limit while testing both the smaller batch and full-limit UI flow

## [0.12.0] - 2026-11-17

### Changed
- Add 100 reviewed Basic D&D and AD&D books to reconciliation and the gated startup catalog, bringing the cumulative batch to 334 entries
- Verify preservation of all 234 existing approvals and full-limit bulk application against the latest diagnostic

## [0.11.0] - 2026-11-17

### Changed
- Add 100 verified AD&D 1e and 2e books to reconciliation and the gated startup catalog while preserving all 134 prior entries
- Verify a full 100-mapping transaction with one backup and safe multi-transaction upgrades without changing the existing limit

## [0.10.0] - 2026-11-17

### Changed
- Add 50 verified AD&D 2e sourcebooks and adventures to both reconciliation and the gated startup catalog, retaining 84 prior approvals
- Verify skipped-version reconciliation above 100 cumulative entries using separately confirmed, backup-backed transactions without raising the per-request limit

## [0.9.0] - 2026-11-17

### Changed
- Add 50 verified AD&D 2e adventures to reconciliation and the gated startup catalog in one release, preserving all 34 prior approvals
- Retain backup-backed atomic mapping, local IDs and personal data, and skip unapproved entries without creating duplicates

## [0.8.0] - 2026-11-17

### Changed
- Promote 34 reviewed adventures into the shared startup catalog while retaining reconciliation gates and approved local identities
- Keep unapproved entries and fresh installations gated; preserve existing records, deletion markers, and PDF indexes on restart

## [0.7.0] - 2026-11-17

### Changed
- Add bulk selection, selection counts, and visible in-progress status to catalog reconciliation with up to 100 mappings per backup-backed transaction
- Expand the reviewed Basic D&D reconciliation batch by 22 adventures while retaining all existing mappings

## [0.6.3] - 2026-11-17

### Changed
- Add five verified Basic D&D adventures to the opt-in reconciliation batch, preserving all seven previously approved mappings

## [0.6.2] - 2026-11-17

### Changed
- Expand the opt-in catalog reconciliation batch with five verified Basic D&D adventures while retaining existing mappings

## [0.6.1] - 2026-11-17

### Changed
- Fix Docker builds by including the catalog pilot manifest in the build context

## [0.6.0] - 2026-11-17

### Changed
- Add opt-in reviewed catalog pilot mappings with automatic database backups and stale-preview protection
- Preserve local IDs and personal data across seeding and mapped-record deletion; recognize compound product codes

## [0.5.0] - 2026-11-17

### Changed
- Add an admin-only read-only catalog reconciliation preview and ID-bearing diagnostic export
- Preserve all local records and omit stored PDF/cover paths, notes, indexed text, and file contents from diagnostics

## [0.4.0] - 2026-11-17

### Changed
- Add Has No Linked PDF filtering to My Collection, with bookmark persistence and per-release behavior when showing every release separately.
- Add Current filtered view CSV export using the active collection filters, sort order, and release visibility options while preserving existing inventory exports.

## [0.3.0] - 2026-11-17

### Changed
- Add publisher filtering and sorting, including books with no publisher set; preserve selections in bookmarked views and refresh publisher choices after edits.

## [0.2.0] - 2026-11-17

### Added
- A single version source, release preparation/check commands, and a documented Git-tagged release workflow.
- Release notes accessible from Help & About.
- Regression tests for collection persistence, PDF indexing, database connections, and frontend behavior.

### Fixed
- Deleted catalog books and releases no longer return after reseeding.
- Explicit shelf-default choices survive catalog updates without creating duplicate defaults.
- Forced PDF reindex requests made during processing retain their force flag.
- Bookmarked sort directions survive reloads.
- Database connections close after success, rollback, setup failures, and commit failures.

### Changed
- PDF covers render outside database write transactions, preserving uploads made during rendering.
- Box-content queries and PDF indexing queue writes are batched.
- Cover-size rendering is coalesced per animation frame.
- PDF status polling slows when idle, paused, or offline and stops in hidden tabs.
- Direct runtime dependencies are pinned while retaining Python 3.10 support.
- Removed unused code and stale styles; refreshed help text and catalog counts.

## [0.1.0] - 2026-11-15

### Added
- Initial displayed app version and Help & About dialog.
- Baseline collection browsing, editing, PDF linking, and Docker OCR worker support.
