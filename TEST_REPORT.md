> Historical document supplied with 1.7. Its completion/testing claims are not validated by this session. Use docs/REVIEW_2_0.md and current code for 2.0 status.

# 1.7.0 validation — 2026-10-30

87 passed, zero skipped/errors/failures; tests-results.xml. Includes 69 existing regressions plus 18 parameterized route/cache/transcriber checks. The four identity combinations assert no direction because identity translation is not offered.

Real CPU inference executed for all 12 ordered nonidentity language pairs (ar/en/tr/ko), with pinned archives downloaded from the official Argos data host. Outputs recorded in language-inference-results.json. Pivot outputs show semantic drift, e.g. Turkish today became English here; quality is not guaranteed. Four new archives SHA256-pinned; archive extraction preserves explicit file allowlist and validates language metadata. Actual extraction/inference passed for all four new models.

Speech routing selects multilingual base for tr/ko; cache keys include the source language. This test is routing only: no actual Turkish/Korean acoustic recognition or Windows font/GUI test performed. Windows EXE not built here. Build scripts now smoke-test six direct model directions, including Hangul output, before and after packaging.

Prior Pinterest/HLS fix remains; no new live platform download run for 1.7.0.
