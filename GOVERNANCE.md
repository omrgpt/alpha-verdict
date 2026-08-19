# Governance

AlphaVerdict uses a lightweight maintainer model during alpha.

## Roles

- **Contributors** submit issues, documentation, tests, code, or review.
- **Reviewers** are recurring contributors trusted to review a defined area.
- **Maintainers** merge changes, cut releases, manage security reports, and protect
  project scope.

The initial maintainer is `@omrgpt`. Roles are earned through sustained, constructive,
security-conscious contributions—not star count or financial claims.

## Decisions

Routine changes use pull-request consensus. Breaking contracts, scope changes, new
network boundaries, or changes to verdict semantics require an Architecture Decision
Record. Maintainers seek consensus; if it cannot be reached, the lead maintainer makes
and documents the decision.

## Independence and conflicts

Contributors must disclose material interests in data vendors, brokers, strategy
products, or services affected by a proposal. Sponsorship does not buy roadmap,
verdict, or merge authority.

## Releases

Releases require green CI, an updated changelog, package build verification, a
security review proportional to the change, and signed or attested artifacts where
supported. Security fixes may follow an embargoed process.

## Changes to governance

Governance changes require a public pull request open for at least seven days once the
project has more than one maintainer. During the initial single-maintainer phase, every
change must still be documented in history.
