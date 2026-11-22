# SciMed SRMA Scout Cloud Architecture

## Purpose

SciMed SRMA Scout Cloud is a mobile-first, publication-oriented discovery and verification system for systematic review and meta-analysis topics across study designs.

## Core design

The system separates deterministic research safeguards from AI-assisted interpretation.

- Deterministic engine: source states, study-family counts, synthesis usability, locked gates, Type-A blocking logic, audit logs.
- AI layer: candidate generation, PICO refinement, semantic overlap interpretation, clinical rationale, editorial stress testing.
- External evidence layer: PubMed, Europe PMC, OpenAlex, Crossref, ClinicalTrials.gov, PROSPERO, OSF and additional registries when relevant.
- Persistence layer: project checkpoints, source logs, candidate ledger and final review packages.
- Final review layer: independent ChatGPT Plus review of the exported evidence package.

## Fail-closed source rule

A source failure must never be converted into a negative search result. Supported states are:

- SEARCHED_NEGATIVE
- SEARCHED_POSITIVE
- PARTIAL
- ACCESS_FAILED
- NOT_SEARCHED
- MANUAL_VERIFIED

## Locked final-review option requirements

Every candidate admitted to the final-review list must be FIRST-CHOICE eligible: all locked gates passed, at least four verified independent eligible studies, at least four verified synthesis-usable studies, conclusive required source coverage, and no unresolved Type-A issue. Pending, provisional, incomplete, or gate-failing candidates are excluded even when this leaves fewer than the requested number of final options. The engine does not select the overall winner. ChatGPT compares only the fully qualified options.
