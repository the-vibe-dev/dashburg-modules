from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Persona:
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    city: str
    state: str
    zip_code: str
    company: str
    username: str
    password: str
    website: str


def persona_from_seed(seed: int = 7) -> Persona:
    rnd = random.Random(seed)
    first = rnd.choice(["Alex", "Jordan", "Taylor", "Sam", "Morgan", "Avery"])
    last = rnd.choice(["Carter", "Lee", "Brooks", "Diaz", "Patel", "Nguyen"])
    username = f"{first.lower()}.{last.lower()}{rnd.randint(10, 99)}"
    return Persona(
        first_name=first,
        last_name=last,
        email=f"{username}@example.test",
        phone=f"555{rnd.randint(1000000, 9999999)}",
        address=f"{rnd.randint(100, 9999)} Test Avenue",
        city=rnd.choice(["Austin", "Seattle", "Boston", "Miami", "Denver"]),
        state=rnd.choice(["TX", "WA", "MA", "FL", "CO"]),
        zip_code=str(rnd.randint(10000, 99999)),
        company=rnd.choice(["Acme Labs", "Northwind", "Bluebird Systems"]),
        username=username,
        password="P@ssw0rd!234",
        website="https://example.test/profile",
    )


def classify_field(name: str) -> str:
    n = str(name or "").lower()
    mapping = {
        "email": "email",
        "phone": "phone",
        "mobile": "phone",
        "zip": "zip",
        "postal": "zip",
        "address": "address",
        "city": "city",
        "state": "state",
        "company": "company",
        "user": "username",
        "pass": "password",
        "date": "date",
        "time": "time",
        "search": "search",
        "comment": "comments",
        "message": "comments",
        "url": "url",
        "website": "url",
        "name": "name",
    }
    for token, cls in mapping.items():
        if token in n:
            return cls
    return "text"


def value_for_class(field_class: str, persona: Persona, mode: str = "realistic") -> Any:
    cls = str(field_class or "text")
    if mode == "invalid":
        invalids = {
            "email": "not-an-email",
            "phone": "abc",
            "zip": "12",
            "url": "notaurl",
            "password": "1",
        }
        if cls in invalids:
            return invalids[cls]
    if mode == "max-length":
        return "X" * 200

    values = {
        "name": f"{persona.first_name} {persona.last_name}",
        "email": persona.email,
        "phone": persona.phone,
        "address": persona.address,
        "city": persona.city,
        "state": persona.state,
        "zip": persona.zip_code,
        "company": persona.company,
        "username": persona.username,
        "password": persona.password,
        "date": "2026-01-15",
        "time": "13:45",
        "search": "browser automation regression",
        "comments": "Automated test submission for QA validation.",
        "url": persona.website,
        "text": persona.first_name,
    }
    return values.get(cls, persona.first_name)
