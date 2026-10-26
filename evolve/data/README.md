The exercise_hints.json catalogue is imported from Free Exercise DB:
https://github.com/yuhonas/free-exercise-db

The snapshot records its full source commit, retrieval date, source links and
license. Of 876 source exercises, 868 have both photos and written instructions;
eight incomplete entries are excluded. Instructions, muscle groups, equipment,
difficulty and category are retained from the source. Equivalent-name aliases
added by EVOLVE live separately in evolve/exercises.py. Ambiguous names and
different equipment or movement variations do not fall back to another exercise.

The source dataset is released under The Unlicense. Its original license text
is retained in free-exercise-db-LICENSE.txt. The viewer credits Free Exercise DB
and links to the exercise's source record and The Unlicense.

Photos are resized to fit within 480 × 480 pixels and encoded as WebP (quality
75) in evolve/static/exercise-images/. Content hashes in filenames allow long
browser caching and deduplicate identical photos. All images and instructions
are served locally: no API key, provider request or video playback is needed.
Only opening a hint requests its photos; written instructions display immediately.

Refresh from the project root after installing requirements-dev.txt, then restart
Flask to clear the in-memory name index:

    python scripts/refresh_exercise_hints.py

The importer defaults to the pinned source commit. To update it, supply a full
commit SHA with --revision. To use an already downloaded GitHub source tarball,
add --archive /path/to/source.tar.gz (and its --revision if it differs).
The existing catalogue is kept if source validation or image conversion fails.
Old, unused photos are kept so previously rendered pages continue to work.
