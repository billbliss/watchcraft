# Display-label normalization and protected forms

- Document type: Architecture note
- Status: Describes the implemented Watchcraft policy
- Date: 2026-09-13

## Purpose

This note records the reusable design behind Watchcraft's topic-label normalization. The problem appears cosmetic but is semantic: a reader needs calm, consistent labels without destroying meaningful casing in notation, acronyms, names, brands, products, or model identifiers. The approach is relevant to any derived vocabulary layer, including future Filmcraft entities and annotations.

## Separate identity from presentation

A topic's canonical key and its display label serve different purposes. The canonical key is case-insensitive semantic identity used for matching, deduplication, relationships, and stable IDs. The display label is presentation data that may be refined without changing that identity.

For example:

```json
{
  "canonical_key": "mazda mx-5 miata",
  "display_label": "Mazda MX-5 Miata",
  "protected_forms": ["Mazda", "MX-5", "Miata"]
}
```

Changing display policy must not rewrite raw observations, aliases, canonical keys, or topic identity.

## Policy

Watchcraft uses lowercase for ordinary language. It preserves exact conventional casing only when casing carries meaning or identifies a named entity.

Examples:

- ordinary language: `internal combustion engine`, `spring compressor`, `camshaft drive`;
- notation and technical forms: `i-hat`, `pH`, `H.264`, `3D`;
- platforms and brands: `macOS`, `YouTube`, `DaVinci Resolve`;
- makes, products, and models: `Mazda MX-5 Miata`, `Holley HP EFI`, `Vintage Air accessory drive`.

This is not a title-casing algorithm and does not depend on a product-specific whitelist.

## Processing contract

The display-label stage asks the model for both a compact label and the exact substrings whose casing must be protected. A protected form is accepted only when it appears in the proposed label and is grounded in the topic's corpus evidence. Generic words cannot be protected merely because an input happened to capitalize them.

Accepted protection metadata is stored in the immutable topic-normalization artifact beside the display-label map. It is durable processing data, not a temporary explanation from the model:

```json
{
  "display_labels": {
    "mazda mx-5 miata": "Mazda MX-5 Miata"
  },
  "display_label_protected_forms": {
    "mazda mx-5 miata": ["Mazda", "MX-5", "Miata"]
  }
}
```

The deterministic casing pass masks protected forms, lowercases the remaining text, and restores the protected forms exactly. Intrinsically cased forms such as `H.264`, `3D`, `pH`, and `macOS` also receive deterministic protection, but single-word names such as `Mazda` require the grounded model decision because their spelling alone is ambiguous.

Terminology resolution can replace observed forms after initial label generation. It must therefore transform the protected forms together with the label and rerun the same deterministic casing policy. Compilation consumes the final normalized label; the reader displays it without inventing another casing policy.

```text
raw topics and chapter context
             │
             ▼
compact label + grounded protected forms
             │
             ▼
deterministic lowercase policy
             │
             ▼
terminology substitutions + transformed protection
             │
             ▼
deterministic lowercase policy again
             │
             ▼
compiled display label
```

## Why the intermediate approaches failed

### Universal title case

Mechanical title casing produced visually noisy chips and mishandled vocabulary such as `i-hat`. Model-generated capitalization was also inconsistent across a collection.

### Lowercase without protection

Lowercasing everything fixed visual consistency but damaged proper names and branded forms, producing labels such as `mazda MX-5 miata`.

### Temporary protected forms

The model initially returned `protected_forms`, but the pipeline used them only while generating the first label and then discarded them. A later terminology pass could no longer distinguish `Mazda` from an accidentally capitalized ordinary word. Protection must survive for as long as downstream transformations can rewrite the label.

### Rendering-time correction

The reader lacks the evidence required to distinguish meaningful casing from accidental casing. Correcting labels during rendering would create platform-specific behavior and leave published data inconsistent. Normalization belongs in the authoring pipeline.

### Whitelists

A fixed list of brands or names cannot scale across collections and domains. The durable representation is a grounded decision tied to the corpus and processing provenance.

## Versioning and reruns

Prompt policy, validation behavior, and downstream casing semantics are material inputs. A change bumps the prompt and handler versions in the capability registry. Because job identity binds the complete specification, rerunning the same project plan creates a new immutable normalization job while leaving earlier artifacts intact. A new normalization digest then produces a new compilation job and review package.

This makes policy correction explicit and reproducible. Deploying a registry does not mutate previously generated collections; normalization, compilation, materialization, and installation of the new review package are separate steps.

## Required tests

Tests should cover the complete transformation chain rather than only the model response:

- ordinary words become lowercase;
- grounded single-word and multiword names retain exact casing;
- notation, acronyms, and mixed-case brands retain exact casing;
- unsupported protected forms are rejected;
- terminology substitutions preserve or transform protection metadata;
- duplicate-label fallback still produces unique lowercase labels;
- old artifacts without protection metadata remain readable; and
- compilation and materialization preserve the final labels without reader-side correction.

The regression corpus should retain representative failures such as `camshaft Drive`, `gasket Sealing`, `i_hat`, `mazda MX-5 miata`, and `DaVinci Resolve`.

## Filmcraft application

Filmcraft is likely to encounter this problem more often. Candidate protected forms include people, characters, studios, production companies, film titles, fictional vocabulary, cameras, lenses, codecs, color spaces, software, and edition-specific terminology. The same architecture applies: immutable raw observations, case-insensitive semantic identity, a separately authored display form, grounded protection metadata, provenance, and deterministic validation after every transformation.

Some Filmcraft entities will eventually deserve first-class entity identity rather than remaining protected strings. This policy is still useful at ingestion and presentation boundaries, and it provides a clean migration path: a protected form can later resolve to an entity without changing the underlying raw evidence.
