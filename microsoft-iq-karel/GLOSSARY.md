# Karel a dodávka, která nedorazí

Demo k přednášce o Microsoft IQ: AI agent Karel pomáhá provozní ředitelce fiktivní
firmy Contoso Moravia a.s. připravit rozhodnutí o výpadku dodávky a s každou přidanou
vrstvou kontextu odpovídá lépe.

## Agent a kontext

**Karel**:
AI agent, který pomáhá provozní ředitelce Janě Králové s rozhodnutím o výpadku dodávky.
_Avoid_: bot, asistent, robot

**Verze agenta**:
Jeden z kroků v0–v4. Každý krok je samostatný Karel, který má oproti předchozímu o jednu IQ vrstvu víc.
_Avoid_: krok, level, stupeň

**IQ vrstva**:
Jeden ze čtyř zdrojů kontextu Microsoft IQ (Fabric IQ, Foundry IQ, Web IQ, Work IQ), kterým se Karel postupně učí.
_Avoid_: IQ nástroj, plugin, konektor

**Demo otázka**:
Neměnná otázka, kterou Jana pokládá každé verzi agenta: „Northwind posouvá dodávky K-200 o 3 týdny. Co mám udělat? Připrav mi doporučení na poradu vedení ve 14:00.“
_Avoid_: prompt, dotaz

**Persona**:
Fiktivní postava z příběhu, za kterou v demu vystupuje skutečný přihlášený uživatel nebo vložená data.
_Avoid_: uživatel, účet

## Výroba a nákup

**Ohrožená objednávka**:
Zákaznická objednávka s výrobkem obsahujícím K-200 a termínem dodání do 21 dní, jejíž potřebu nepokryje zásoba po přidělení objednávkám s dřívějším termínem (při shodě termínu dostane zásobu objednávka s vyšší hodnotou).
_Avoid_: kritická zakázka, riziková objednávka

**Mimořádná událost**:
Výpadek dodávek, kvůli kterému firma nakupuje mimo běžný plán; zde posun dodávek K-200 od Northwindu.
_Avoid_: incident, krize

**Mimořádný nákup**:
Souhrn všech nákupů k jedné mimořádné události; schvalovací limit 2 mil. Kč se posuzuje na tento souhrn, ne na jednotlivé objednávky.
_Avoid_: nouzová objednávka, urgentní nákup

**Schválený druhý zdroj**:
Dodavatel kvalifikovaný v registru jako náhrada za hlavního dodavatele dané komponenty; pro K-200 je to Tailwind Components.
_Avoid_: alternativní dodavatel, záložní dodavatel
