The exercise_demos.json catalogue is a filtered snapshot of the public wger API:
https://wger.de/api/v2/exerciseinfo/

Only English entries with real video media are retained. The retrieved_at field
records the fetch date. The snapshot retains source names and aliases, records
their authors and licenses, and selects one original video URL per exercise,
preferring H.264/MP4 and then smaller files. Video files are neither copied nor
modified. Videos in this snapshot are licensed CC BY-SA 4.0 by their credited
authors; source name metadata also includes CC BY-SA 3.0 entries. Each entry
records its own author and license URL. Keep these credits when reusing data.

The viewer displays the selected video's creator, license, original-video link,
and database source. Equivalent-name aliases added by EVOLVE live separately in
evolve/exercises.py. No exercise descriptions or instructions are redistributed.

Refresh from the project root with:
    python scripts/refresh_exercise_demos.py

wger API documentation: https://wger.readthedocs.io/en/latest/api/api.html
CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/
CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/
