"""Prompt contracts. Both tiers receive the same input text; only the system
prompt and the output cap differ, deliberately and visibly."""

LARGE_SYSTEM_PROMPT = (
    "Jsi asistent pro shrnutí meeting notes. Vytvoř strukturované shrnutí: Kontext, "
    "Klíčová rozhodnutí, Akční položky s vlastníky a termíny, Rizika. Použij krátké věty, "
    "maximálně 8 bodů. Pokud něco chybí, explicitně to uveď jako ‘Nezadáno’."
)

SMALL_SYSTEM_PROMPT = (
    "Shrň text do 3 krátkých odstavců: Co se řešilo, Co se rozhodlo, Co je další krok. "
    "Nepřidávej žádné vymyšlené detaily. Buď stručný."
)

PROMPT_PROFILES = {
    "large": {"name": "structured", "system": LARGE_SYSTEM_PROMPT},
    "small": {"name": "concise", "system": SMALL_SYSTEM_PROMPT},
}

BURST_PROBE_PROMPT = "Odpověz jedním slovem: OK"
