"""Fictional-city inventory lab, isolated from the Madrid delivery fixture."""

from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb

from delivery.catalogue import load_catalogue
from delivery.city import fake_city
from delivery.db import connect, migrate
from delivery.inventory import movement


def create_lab(
    url: str | None = None, seed: int = 42, catalogue_path: Path = Path("data/lab-catalogue.json")
) -> str:
    migrate(url)
    catalogue = load_catalogue(catalogue_path)
    city = fake_city(seed)
    run = str(uuid4())
    selected = f"{catalogue.products[0].source}:{catalogue.products[0].listing_id}"
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO runs(id,seed,duration,wall_seconds) VALUES (%s,%s,900,0)", (run, seed)
        )
        conn.execute(
            "INSERT INTO lab_worlds VALUES (%s,%s,%s,%s,%s)",
            (
                run,
                Jsonb(city),
                Jsonb(catalogue.model_dump(mode="json")),
                catalogue.digest(),
                selected,
            ),
        )
        for store in city["stores"]:
            for product in catalogue.products:
                sku = f"{product.source}:{product.listing_id}"
                count = 1 if sku == selected else 10
                conn.execute(
                    "INSERT INTO lab_stock(run_id,store,sku,on_hand) VALUES (%s,%s,%s,%s)",
                    (run, store["id"], sku, count),
                )
                movement(
                    conn,
                    run,
                    f"opening:{store['id']}:{sku}",
                    store["id"],
                    sku,
                    0,
                    "opening",
                    count,
                    0,
                )
        conn.execute(
            """INSERT INTO lab_shipments(run_id,id,store,sku,quantity,expected_sim)
                     VALUES (%s,'supply-1','store-1',%s,5,300)""",
            (run, selected),
        )
    return run
