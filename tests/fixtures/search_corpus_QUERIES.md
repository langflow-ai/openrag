# Search test queries

Ingest only the 11 `.md` files in `search_corpus/` (not this file). Use a small chunk size (about 500 characters, no overlap) so each `[Cnn]` section stays its own chunk.

## Gibberish (expect no results; first six rows skip kNN, the rest rely on the noise-floor filter)

| Query | Tests | Expected |
|---|---|---|
| dddd | repeated letter | none |
| xx | short repeated letter | none |
| dnfjdisfhds | keyboard mash | none |
| asdkfjhasd | mash with vowels | none |
| fdjsdifnsji | mash | none |
| dddd xx | multi-word all noise | none |
| dnfjdisfhds parsing | mash plus real word (kNN runs) | C21-C25 only, no noise hits |
| zorbnaxle | invented word, not caught by regex | none or Low only |
| quantum blockchain | off-topic real words | none or Low only |

## Must not be flagged as gibberish

| Query | Tests | Expected |
|---|---|---|
| strengths | vowel-poor word | C41 |
| https | vowel-poor acronym | C42 |
| pgsql | vowel-poor acronym | C42 |
| xhtml | vowel-poor acronym | C42 |
| rhythms | no vowels but y | C43 |
| twelfths | long consonant cluster | C43 |
| blorfwump | rare real term, looks like mash | C44 top |

## Semantic (medium relevance must survive)

| Query | Tests | Expected |
|---|---|---|
| parsing tools | keyword plus semantic | C23 High; C21, C22, C24, C25 Medium |
| scanned documents to JSON | semantic only | C21 |
| table extraction accuracy | semantic only | C22, C25 |
| harbor cargo delays | semantic only | C01, C03 |
| consensus algorithm | semantic plus one keyword | C06 top; C07-C10 |
| leader election | semantic | C06, C07, C10 |
| cure for tiredness | semantic, no shared words | C16-C19 Medium |
| dosage | semantic | C19 |
| who opened the bridge | natural-language question | C12 |
| container throughput drop | cross-language semantic | C01, C36, C38 |
| tram scheduler | cross-file | C44, C15 |

## Zero keyword overlap (vector leg only)

Every word in these queries was checked against the whole corpus, allowing one or two typos and prefix matches (the same fuzziness the app uses). None matches any word in any chunk, so a result here can only come from embeddings. Scores come from the vector leg alone, so expect Medium at best.

| Query | Related to | Expected |
|---|---|---|
| tiredness remedy | Trial OR-212 (cobalt fatigue) | C16, C17, C18, C19 |
| weariness therapy | Trial OR-212 | C16, C17 |
| puppy | Biscuit the dog, canine enrichment | C26, C28 |
| puppies | same | C26, C28 |
| puppy veterinary | same | C26, C28 |
| wharf accident | Pier Nine crane failure, barge grounding | C03, C01 |
| shipwreck rescue | barge grounding | C01, C03 |
| dockside maritime | port reports | C01, C03, C36, C38 |
| automated bookkeeping | invoice intake pipeline | C21, C22, C25 |
| paperwork digitisation | invoice intake pipeline | C21 |
| civic infrastructure | Lumen Footbridge | C12 |
| inauguration footpath | Lumen Footbridge | C12 |
| streetcar | tram scheduler | C44, C15 |

Pass if the related chunks appear as Medium or better and unrelated chunks stay Low. Fail if an unrelated chunk (for example C27, "log") ranks High.

Unrelated controls (no keyword overlap and no related chunk; expect none or Low only): `volcano`, `cryptography`.

## dog / log accuracy

| Query | Tests | Expected |
|---|---|---|
| dog | no "dog" matching "log" | C26 top; C28, C30 Medium; C27 not High |
| log | exact short word | C27, C30 |
| dogs | plural, one-edit fuzz | C30 top |
| logs | plural | C30 |
| canine | synonym | C28 High; C26, C30 Medium |

## Exact tokens and IDs

| Query | Tests | Expected |
|---|---|---|
| KV-4471-B | exact SKU narrowing | C31 top (C32 same file) |
| KV-4471 | partial SKU | C31, C32 |
| ZT-0082 | SKU | C33 |
| v3.2.9 | version, two chunks | C34, C08 |
| v3.2.9-rc2 | version with suffix | C08 top |
| veln_quorum_ttl | snake_case key | C07 |
| VQ-5530 | issue ID | C08 |
| MMB-2291-0446 | long ID | C20 |
| TQ-90-117 | customs code | C02 |
| WF-19 | form code | C35 |
| CAL-7710 | certificate | C33 |
| 22-B | short ordinance | C11 |

## Typos, prefixes, lookalikes

| Query | Tests | Expected |
|---|---|---|
| Tessalun | one-letter typo | C01, C04 (plus other Tessalune chunks) |
| Velquorn | typo | C16, C17, C18, C20 |
| velqu | prefix | C16, C17, C18, C20 |
| Thornwick | lookalike name | C45 top; C46 lower |
| Thornwich | lookalike name | C46 top; C45 lower |
| halverstone ledger | case-insensitive | C50 |
| Brenthorne Vale | hyphenated name split | C12 |
| O'Brannigan-Seo | apostrophe and hyphen | C03 |

## Languages and symbols

| Query | Tests | Expected |
|---|---|---|
| puerto | Spanish | C36 |
| Straßenbahn | German eszett | C37 (C15 via semantic) |
| 港 | single CJK character | C38 |
| phare | French | C39 |
| c++ | symbols in query | C40 |
| §4.2(b) | section sign | C40 |
| ops@tessalune.invalid | email | C40 |

## Foreign-language corpus (`11_foreign_languages.md`, C51-C64)

Expectations come from the chunk text; they have not been run against an index yet. Port report (same story as C01) in French C51, German C52, Portuguese C53, Italian C54, Russian C55, Arabic C56, Korean C57, Chinese C58, Hindi C64, plus the existing Spanish C36 and Japanese C38. Dog story (C26) in Dutch C59, Norwegian C60, Turkish C61. Footbridge (C12) in Turkish C62 and Greek C63.

| Query | Tests | Expected |
|---|---|---|
| baisse du trafic de conteneurs | French query, French chunk | C51 top |
| Containerbewegungen Rückgang | German query, German chunk | C52 top |
| queda de contentores | Portuguese query | C53 top |
| calo dei container | Italian query | C54 top |
| контейнерные операции | Russian query, Cyrillic | C55 top |
| حاويات الميناء | Arabic query, right-to-left script | C56 top |
| 컨테이너 물동량 | Korean query, Hangul | C57 top |
| 集装箱 港务局 | Simplified Chinese query | C58 top |
| कंटेनर बंदरगाह | Hindi query, Devanagari | C64 top |
| container throughput drop | English query, any-language port chunk | C01 plus C36, C38, C51-C58, C64 as semantic hits |
| porto franco | Portuguese and Italian share the phrase | C53, C54 |
| Ombrelle Dray | Latin-script name in every port chunk | C01, C36, C51-C54, C57 keyword hits |
| Омбрель Дрэй | Same name transliterated to Cyrillic | C55 |
| 翁布雷尔 | Same name in Chinese | C58 |
| hond asiel | Dutch query | C59 top |
| hundehjem | Norwegian query | C60 top |
| köpek barınak | Turkish query | C61 top |
| dog shelter adoption | English query for the dog story | C26 plus C59, C60, C61 as semantic hits |
| köprü açılışı | Turkish query | C62 top |
| γέφυρα εγκαίνια | Greek query | C63 top |
| bridge opening ceremony | English query for the footbridge | C12 plus C62, C63 as semantic hits |
| Straßenbahn | Existing German tram chunk, not the port report | C37 |
| ß | Single special character | none or low |
| 港 | Single CJK character | C38 keyword hit; C58 only as semantic |
| 港口 | Chinese word for port | C58 keyword hit |
| 港の報告 | Japanese phrase, shares 港 with Chinese | C38 top |
| 日本語 | Word absent from the corpus | none or low |
| Тессалюн | Cyrillic spelling of Tessalune | C55 |
| تيسالون | Arabic spelling of Tessalune | C56 |
| 테살룬 | Korean spelling of Tessalune | C57 |

## Multi-file and edge

| Query | Tests | Expected |
|---|---|---|
| Marenth | term across files | C01, C03, C09, C27 |
| Wexmoor | term across two files | C02, C45 |
| Pale Heron | phrase across files | C05, C39 |
| Pale Heron survey vessel | longer phrase | C05 top |
| Velquorin side effects | topic plus drug name | C18 top |
| fraud | negated mention | C47 (keyword hit) |
| 1.25 million | number format variants | C48 |
| the of and | stopwords only | none or C49 weak |
| * | wildcard | all 50 chunks, no tiers |
