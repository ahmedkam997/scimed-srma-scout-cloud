# SciMed SRMA Scout Cloud Architecture

## Purpose

SciMed SRMA Scout Cloud is a mobile-first, publication-oriented discovery and verification system for RCT-only systematic review and meta-analysis topics.

## Core design

The system separates deterministic research safeguards from AI-assisted interpretation.

- Deterministic engine: source states, trial-family counts, numerical usability, locked gates, Type-A blocking logic, audit logs.
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

## Locked first-choice RCT-only requirements

A final PROCEED decision requires all locked gates, including at least seven verified independent randomized populations, at least seven verified quantitatively usable RCTs, no unresolved Type-A issue, adequate novelty, clinical importance, publication potential and editorial stress-test performance.
