"""Demo inputs. The short notes stay well under the gateway token limit; the long
transcript is sized (roughly 4-6k tokens) to reliably exceed it."""

SHORT_NOTES = """Weekly sync – projekt Helios, 14. 5.
Účastníci: Jana (PM), Petr (backend), Lucie (UX), Tomáš (data).

Probrali jsme zpoždění integrace platební brány. Petr potvrdil, že sandbox od dodavatele funguje, ale chybí produkční certifikát. Rozhodli jsme, že release 2.3 posuneme o týden na 28. 5. Jana o posunu informuje obchod do pátku. Lucie dokončí nový onboarding flow do středy, Tomáš připraví dashboard konverzí do konce sprintu.

Riziko: pokud certifikát nedorazí do 21. 5., ohrozí to i termín 28. 5. Petr eskaluje u dodavatele ještě dnes. Další sync bude ve čtvrtek."""

LIMIT_TEST_INSTRUCTION = (
    "Z tohoto textu vytvoř detailní zápis, přepiš ho do přehledné struktury, "
    "navrhni alternativy a přidej doporučení."
)

_TRANSCRIPT_BLOCKS = [
    """[09:00] Jana (PM): Dobré ráno, začneme. Dnešní agenda je čtvrtletní plánování platformy Helios: stav migrace do cloudu, výkon API, platební brána, mobilní aplikace, datová platforma, bezpečnostní audit, rozpočet a nábor. Prosím držte se času, máme na to dvě hodiny a každý blok má zhruba patnáct minut.
[09:02] Petr (backend): Začnu migrací. Máme přesunuto sedmdesát procent služeb do Azure Container Apps. Zbývá billing, reporting a starý integrační modul pro partnery. Billing je nejsložitější, protože používá sdílenou databázi s reportingem a má noční dávkové úlohy, které běží přes tři hodiny. Navrhuji rozdělit databázi, ale to znamená minimálně čtyři týdny práce dvou lidí.
[09:06] Tomáš (data): Z pohledu dat bych rozdělení databáze podpořil, ale potřebujeme zachovat historii transakcí za posledních sedm let kvůli auditu. Pokud databázi rozdělíme, musíme vyřešit, kde bude archiv a jak se k němu dostane reporting. Jedna varianta je přesunout archiv do datového jezera a reporting napojit přes Fabric.
[09:09] Martin (architekt): S datovým jezerem souhlasím, ale upozorňuji na latenci. Někteří partneři chtějí reporty téměř v reálném čase. Pokud půjdeme přes jezero, dostaneme se na zpoždění desítek minut. Alternativou je ponechat posledních devadesát dní v operační databázi a starší data archivovat.""",
    """[09:14] Jana (PM): Dobře, rozhodnutí o databázi odložíme na konec, chci slyšet i ostatní bloky. Lucie, mobilní aplikace?
[09:15] Lucie (UX): Nový onboarding je hotový v prototypu. Testovali jsme ho s dvanácti uživateli, devět z nich prošlo registrací bez pomoci, tři se zasekli u ověření identity. Problém je, že ověření identity dodává externí služba a její obrazovka nejde stylovat. Navrhuji přidat mezikrok s vysvětlením, co bude následovat, a fallback na ruční ověření přes podporu.
[09:19] Karel (mobile): Technicky je mezikrok jednoduchý, ale fallback na ruční ověření znamená novou frontu pro podporu a nový proces. Podpora už teď hlásí, že nestíhá. Pokud to zavedeme, potřebujeme buď posílit podporu, nebo omezit ruční ověření jen na určité segmenty zákazníků.
[09:22] Eva (podpora): Potvrzuji, máme průměrnou dobu odezvy osmnáct hodin a cíl je osm. Ruční ověření by přidalo odhadem sto padesát tiketů týdně. Bez dalšího člověka to nezvládneme. Navrhuji pilot jen pro firemní zákazníky, kterých je méně a mají vyšší hodnotu.""",
    """[09:26] Jana (PM): Pilot pro firemní zákazníky zní rozumně. Petr, platební brána?
[09:27] Petr (backend): Integrace je hotová v sandboxu. Chybí produkční certifikát od dodavatele, slíbili ho třikrát a pokaždé posunuli. Pokud nedorazí do dvacátého prvního, nestihneme release dvacátého osmého. Mám připravenou alternativu, a to ponechat starou bránu pro stávající zákazníky a novou zapnout jen pro nové registrace, až certifikát dorazí. Nevýhodou je, že budeme dva měsíce udržovat dvě integrace.
[09:31] Martin (architekt): Dvě integrace jsou riziko i z pohledu bezpečnosti, protože stará brána používá zastaralou verzi TLS knihovny. Bezpečnostní tým ji označil jako nález střední závažnosti. Pokud ji necháme déle než do konce kvartálu, musíme to formálně akceptovat jako riziko na úrovni vedení.
[09:34] Simona (security): Ano, a k tomu doplním výsledky auditu. Máme tři nálezy vysoké závažnosti: sdílené servisní účty v CI pipeline, chybějící rotace klíčů u dvou úložišť a přístup vývojářů k produkčním logům s osobními údaji. Termín nápravy je konec příštího měsíce. Doporučuji přejít na managed identity všude, kde to jde, a zavést centrální správu přístupů k modelům AI přes gateway, abychom měli audit, kdo co volá.""",
    """[09:39] Tomáš (data): K AI přístupu, dnes máme pět týmů, které volají jazykové modely přímo s vlastními klíči. Nemáme přehled o spotřebě, minulý měsíc jsme překročili plánovaný rozpočet o čtyřicet procent, protože jeden experiment běžel přes víkend v nekonečné smyčce. Centrální gateway s limity na tokeny a náklady by tomu zabránila.
[09:42] Jana (PM): To je důležité, prosím zapište to jako samostatnou iniciativu. Kdo by ji vlastnil?
[09:43] Martin (architekt): Můžu ji vzít já s Tomášem. Potřebujeme definovat limity per tým, fallback na levnější modely při překročení a jednotné logování. Odhad jsou tři týdny na pilot.
[09:45] Karel (mobile): Za mobilní tým, my používáme model pro sumarizaci recenzí v obchodě. Pokud nás přepnete na menší model, kvalita klesne. Chtěli bychom vědět předem, kdy k tomu dojde, a mít to vidět v metrikách.
[09:47] Simona (security): To je přesně důvod pro audit trail. Každé rozhodnutí gateway, tedy povolení, odmítnutí nebo přepnutí modelu, musí být dohledatelné s identitou volajícího a důvodem.""",
    """[09:50] Jana (PM): Rozpočet. Finance nám schválily o deset procent méně, než jsme žádali. Musíme škrtnout jednu ze tří velkých položek: rozdělení databáze, posílení podpory, nebo nový datový dashboard pro partnery.
[09:52] Eva (podpora): Bez posílení podpory nesplníme SLA a hrozí smluvní pokuty u dvou největších klientů. Tohle bych neškrtala.
[09:53] Tomáš (data): Dashboard pro partnery můžeme udělat v jednodušší verzi nad stávajícím reportingem, ušetříme tím zhruba šedesát procent nákladů. Nebude to real-time, ale pokryje to osmdesát procent požadavků.
[09:56] Petr (backend): Rozdělení databáze je předpoklad dokončení migrace. Bez něj budeme dál platit za starý on-premise server, což je ročně víc než celý dashboard.
[09:58] Martin (architekt): Navrhuji tedy: rozdělení databáze ano, posílení podpory ano, dashboard ve zjednodušené verzi. Archiv do datového jezera, posledních devadesát dní v operační databázi.""",
    """[10:01] Jana (PM): Nábor. Máme otevřené dvě pozice, senior backend a data engineer. Na backend máme dva finální kandidáty, na data nikoho.
[10:03] Tomáš (data): Na data engineera bych zvážil externí agenturu na šest měsíců, než najdeme interního člověka. Je to dražší, ale nemůžeme čekat.
[10:05] Jana (PM): Dobře. Shrnu, co jsem slyšela, a opravte mě. Release se posouvá na dvacátého osmého, pokud dorazí certifikát. Pokud ne, zapneme novou bránu jen pro nové registrace a starou bránu akceptujeme jako riziko do konce kvartálu. Onboarding s mezikrokem, ruční ověření jen pilotně pro firemní zákazníky. Databázi rozdělíme, archiv do jezera. AI gateway jako nová iniciativa, vlastní Martin a Tomáš. Nápravu bezpečnostních nálezů vlastní Simona, termín konec příštího měsíce.
[10:09] Simona (security): Doplňuji, že potřebuji od každého týmu seznam servisních účtů do příštího pátku.
[10:10] Eva (podpora): A já potřebuji schválení nového člověka do podpory, ideálně tento týden, jinak nástup bude až za dva měsíce.
[10:11] Jana (PM): Schválení zařídím do čtvrtka. Petr eskaluje certifikát u dodavatele dnes. Lucie pošle finální návrh onboardingu do středy. Karel odhadne pracnost mezikroku do pátku. Tomáš připraví návrh architektury archivu do dvou týdnů. Další plánování za měsíc. Děkuji všem.""",
]

LONG_TRANSCRIPT = (
    LIMIT_TEST_INSTRUCTION
    + "\n\nPřepis jednání – čtvrtletní plánování platformy Helios (Q3)\n\n"
    + "\n\n".join(_TRANSCRIPT_BLOCKS)
    + "\n\nPříloha – doplňující poznámky z předchozího jednání, které je potřeba zohlednit:\n\n"
    + "\n\n".join(_TRANSCRIPT_BLOCKS[:3])
)

SAMPLES = {
    "short": {"label": "Short meeting notes (2 paragraphs)", "text": SHORT_NOTES},
    "long": {"label": "Long transcript (exceeds token policy)", "text": LONG_TRANSCRIPT},
}
