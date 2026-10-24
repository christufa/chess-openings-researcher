# Reference book: named opening variations

`a.tsv` … `e.tsv` are the ECO-coded opening names of
[lichess-org/chess-openings](https://github.com/lichess-org/chess-openings) at commit
`a6189a30dc273ccb21fc2536a9a2fefd5592a67a` (2026-10-06), unchanged. They are dedicated to the
public domain (CC0 1.0). Columns: `eco`, `name`, `pgn` (the moves that define the name).

The explorer merges them into the book tree as a reference layer
(`openings_research/reference.py`): every position gets its standard name, and named moves are
offered beside the researched ones. They are names and move orders only, not research.

To update, download the five files at a newer commit and change the commit here and in
`COMMIT` in `reference.py`:

    curl -sfLO https://raw.githubusercontent.com/lichess-org/chess-openings/<sha>/a.tsv
