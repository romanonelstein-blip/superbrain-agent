---
name: marketplace-trust-pilot
description: Review marketplace listings, user safety, seller protection, payment-provider readiness, privacy and acceptance tests for a controlled Fondio beta. Use when planning or testing Fondio features without live payments.
---
# Marketplace Trust Pilot

## Workflow
1. Inspect the actual Fondio application, schema and authorization policies before proposing new features.
2. Check account creation, listing ownership, edit permissions, image access, private messages, moderation and opt-outs using fictional fixtures.
3. Ensure public listings reveal only information intended to be public. Check object and storage access across different users.
4. Model seller and buyer journeys, disputes, prohibited content controls, delivery claims and platform fees.
5. For payments, model payment-intent state, refunds, fees, payouts, retries and webhook idempotency in test mode.
6. Recommend a compliant PSP/marketplace model; account onboarding and provider terms require explicit approval.
7. Record evidence, negative tests and a staged launch decision.
8. Never collect actual customer payment details, charge live cards, create seller payouts or publish before release approval.

## Pilot acceptance
Roles and row permissions work, listing lifecycle is consistent, moderation actions are auditable, failed payments never mark orders fulfilled and all test payments use synthetic data.

## Output
Risk-ranked build backlog, seller-first conversion improvements and binary beta release gates.
