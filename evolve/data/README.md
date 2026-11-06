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


Offline language-region data
----------------------------

language_regions.json.gz contains only CN, TW, HK, MO and SG ranges from DB-IP
Country Lite, with integer IPv4/IPv6 endpoints for binary-search lookups. Source
release, original SHA-256 checksum, attribution, license, and modifications are
recorded inside the file. See db-ip-LICENSE.txt for CC BY 4.0 terms. The public
and workspace footers include the required DB-IP attribution link.

Refresh the snapshot from the project root, then rebuild/restart Flask:

    python scripts/refresh_language_regions.py --month YYYY-MM

The importer validates complete region coverage and non-overlapping ranges before
replacing the existing file atomically. The app performs lookups locally and does
not transmit, persist, or cache individual visitor IPs for this feature.


## Exercise tracking metadata

`exercise_tracking.json` supplements Free Exercise DB, which supplies equipment and instructions but no bodyweight coefficient or logging mode. It maps every bundled exercise ID to a load type, default measurement, and coefficient profile. Existing aliases and Chinese library lookup resolve to the same ID. Membership is explicit: custom names still receive a setup prompt.

Profiles include a source and a plain-language basis. The sources are stored with their URLs in the file:

- [Ebben et al. (2011)](https://pubmed.ncbi.nlm.nih.gov/21873902/) provides peak-force coefficients for standard push-ups (64%) and elevated-hand/foot variations (55% / 70% at about 30 cm elevation). These are tracking estimates, not individualized average force measurements; unspecified heights and hand positions add uncertainty.
- [Hevy's published full-bodyweight convention](https://help.hevyapp.com/hc/en-us/articles/38387131819799-Weighted-Bodyweight-Exercises-Is-Bodyweight-Included-in-Volume) supplies the pull-up/chin-up reference.
- [Kinoku's published coefficient methodology](https://kinoku.app/learn/bodyweight-load-explained) and [reference table](https://kinoku.app/learn/relative-strength-bodyweight-load) provide selected practical estimates and a 70% partial-body fallback. This is a small factual supplement, not an import of its proprietary exercise catalogue.
- [Dempster segment parameters](https://simtk.org/docman/view.php/124/525/NeuromuscularBiomechanicsInertialPropertiesHandout.pdf) supply segment mass fractions. Applying them to leg raises and torso movements is an EVOLVE estimate, not a measured exercise-resistance coefficient.

Plank support uses a prone push-up reference as an estimate. Mobility profiles use a low-load tracking convention. The percentage is not a scientific comparison of effort across different exercises. Supported body mass, moving segment mass, and mechanical leverage differ; custom coefficients remain available under the collapsed adjustment panel.

The table also corrects bodyweight movements whose upstream equipment is `other` or null (for example parallel-bar/ring dips and inverted rows), and distinguishes repetition movements containing “plank” from static holds. Weighted variants remain external-load exercises.

When refreshing the exercise library, update the matching tracking entries and increment the metadata version when changing defaults. The coverage test requires an entry for every library ID. Runtime lookup uses the local file and never sends exercise names or profile weight to an external service.
