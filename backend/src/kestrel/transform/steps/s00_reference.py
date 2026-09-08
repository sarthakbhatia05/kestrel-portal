"""Reference dimensions: regions and outlets.

Applies N5 (city canonicalisation), X1 (soft-deleted), X2 (test and
migration) and X5 (duplicate outlets). X3 (closed outlets) is deliberately
not applied here: it is period-scoped, so it belongs at query time.
"""

import sqlite3

from kestrel.transform.ledger import Action, QualityLedger

name = "s00_reference"

# N5: an explicit, reviewable mapping table. Derived from the distinct city
# values present in the source: Bangalore/Bengaluru and Delhi/New Delhi are
# the only genuine variants; every other value is already canonical.
CITY_MAPPING = {
    "Bangalore": "Bengaluru",
    "New Delhi": "Delhi",
}

TEST_OUTLET_CODE_PREFIX = "TST"


def _canonical_city(raw: str | None) -> str | None:
    if raw is None:
        return None
    return CITY_MAPPING.get(raw.strip(), raw.strip())


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    dst.executemany(
        "INSERT INTO dim_region (region_id, region_code, region_name) VALUES (?, ?, ?)",
        src.execute("SELECT region_id, region_code, region_name FROM regions"),
    )

    outlets = src.execute(
        """
        SELECT outlet_id, outlet_code, outlet_name, channel, city, region_id,
               route_id, salesperson_id, gst_number, status, closed_date, is_deleted
        FROM outlets
        ORDER BY outlet_id
        """
    ).fetchall()

    # X5: a shared GST number identifies the same legal entity captured twice.
    # Outlet names repeat legitimately across the estate and are not a key.
    seen_gst: dict[str, int] = {}
    duplicates: dict[int, int] = {}
    for row in outlets:
        gst = row["gst_number"]
        if not gst:
            continue
        if gst in seen_gst:
            duplicates[row["outlet_id"]] = seen_gst[gst]
        else:
            seen_gst[gst] = row["outlet_id"]

    records = []
    for row in outlets:
        outlet_id = row["outlet_id"]
        rules: list[str] = []

        if row["is_deleted"] == 1 or row["status"] == "DELETED":
            rules.append("X1")
            ledger.record(
                "X1", "Soft-deleted outlet excluded", "outlet", outlet_id,
                Action.EXCLUDED, f"status={row['status']}, is_deleted={row['is_deleted']}",
            )

        if (row["outlet_code"] or "").startswith(TEST_OUTLET_CODE_PREFIX):
            rules.append("X2")
            ledger.record(
                "X2", "Test or migration outlet excluded", "outlet", outlet_id,
                Action.EXCLUDED, f"outlet_code={row['outlet_code']}",
            )

        if outlet_id in duplicates:
            rules.append("X5")
            ledger.record(
                "X5", "Duplicate outlet resolved to surviving entity", "outlet",
                outlet_id, Action.EXCLUDED,
                f"gst_number={row['gst_number']} already held by outlet_id="
                f"{duplicates[outlet_id]}",
            )

        city = _canonical_city(row["city"])
        if city != row["city"]:
            ledger.record(
                "N5", "City name mapped to canonical form", "outlet", outlet_id,
                Action.REPAIRED, f"{row['city']} -> {city}",
            )

        records.append(
            (
                outlet_id, row["outlet_code"], row["outlet_name"], row["channel"],
                row["city"], city, row["region_id"], row["route_id"],
                row["salesperson_id"], row["status"], row["closed_date"],
                1 if rules else 0, ",".join(rules),
            )
        )

    dst.executemany(
        """
        INSERT INTO dim_outlet (
            outlet_id, outlet_code, outlet_name, channel, city_raw, city,
            region_id, route_id, salesperson_id, status, closed_date,
            is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
