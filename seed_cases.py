"""Load the Case of the Day list from a CSV.

Roshansa's task 5 produces this file. Expected columns:

    name,citation,decided,why

Run:  python seed_cases.py cases.csv
"""
import csv
import sys

from src import store


def main(path: str) -> None:
    conn = store.connect()
    store.init(conn)
    with open(path, newline="", encoding="utf-8") as fh, conn.cursor() as cur:
        rows = list(csv.DictReader(fh))
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            cur.execute(
                """INSERT INTO cases (name, citation, decided, why)
                   VALUES (%s,%s,%s,%s)""",
                (name,
                 (row.get("citation") or "").strip(),
                 (row.get("decided") or "").strip(),
                 (row.get("why") or "").strip()),
            )
    conn.commit()
    conn.close()
    print(f"Loaded {len(rows)} cases.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python seed_cases.py cases.csv")
    main(sys.argv[1])
