The v1.3.1 audit of [johncliechty/anchor-plus-skills](https://github.com/johncliechty/anchor-plus-skills) covered every advertised ref: main plus 14 tags, spanning 17 commits, 1,425 current files, 1,499 historic paths, and 1,994 blob/path versions. Provenance is recorded in [public-privacy-audit-2026-09-10.json](public-privacy-audit-2026-09-10.json).

The audit found no private notebooks, datasets, documents, registry files, settings, or credentials in the inspected material. All inspected commits used the author identity `Anchor Publisher <anchor@localhost>`.

It did find personal identifiers: a hostname in source/UI, JSON-escaped local profile paths in an optional Ramanujan manifest, and a personal email assembled in a scanner test. The published v1.3.2 correction removes these from the current release contents while retaining intentional denylist strings, synthetic fixtures, and the public author identity. Recorded validation comprises 103 passing tests and successful validation of the actual exported manifest.

Older public history retains identifiers, including the assembled test email. An ordinary patch release does not rewrite that history. This report describes bounded audit evidence; it is not an absolute guarantee that no personal material exists.

v1.3.2 publication: **Published and fresh-clone verified.**

Release completion: v1.3.2 was published at 2026-09-10T13:44:57.771507+00:00 (commit 7dea2d5aaa70). The exact public clone has 1,429 files; all 1,390 UTF-8 text files passed the strengthened scanner and known-private-marker check. Fresh remote-clone upgrade checks passed. Source changes are committed and pushed to private backups. Historical identifiers remain as described above.
