# Web Application Codebase Architecture Guide

## Purpose

This document describes a reusable architecture for a medium-to-large web application organized as a modular monolith.

It is intended for:

- AI coding agents
- software architects
- developers reproducing the structure in another application
- refactoring an existing Flask or server-rendered web application
- planning a feature-oriented codebase

The structure separates:

- application startup
- configuration
- domain definitions
- persistence
- business logic
- web routes
- templates
- frontend assets
- security
- caching
- runtime user data

The application described here uses Python and Flask, but the architectural principles are framework-independent.

---

# 1. High-Level Architecture

The application is a modular monolith.

A modular monolith has:

- one repository
- one main application runtime
- one deployment unit
- clearly separated internal modules
- shared infrastructure
- feature-specific business logic

Conceptual structure:

```text
Application
├── Bootstrap and runtime startup
├── Configuration and registries
├── Domain definitions
├── Persistence and repositories
├── Business services and workflows
├── Web routes and controllers
├── Templates and reusable UI components
├── Frontend assets
├── Security and encrypted storage
├── Caching and performance
└── Runtime user data
```

The primary architectural rule is:

```text
Routes receive requests.
Services make decisions.
Repositories read and write data.
Templates render output.
Frontend scripts enhance interaction.
```

---

# 2. Layer Responsibilities

## 2.1 Bootstrap Layer

The bootstrap layer starts and assembles the application.

Responsibilities:

- locate the project directory
- locate the runtime data directory
- initialize environment variables
- construct the Flask application
- configure sessions
- initialize authentication
- register middleware and request hooks
- register route blueprints
- register template context processors
- initialize caches
- start the server
- optionally start desktop or mobile wrappers

The bootstrap layer must not contain feature-specific business logic.

Bad example:

```text
Startup script calculates account balances.
```

Good example:

```text
Startup script creates the application and registers the account feature.
```

---

## 2.2 Configuration Layer

The configuration layer describes what the application supports.

Typical contents:

- default settings
- feature flags
- account types
- transaction types
- category defaults
- navigation definitions
- data-file registry
- installation paths
- user-data path resolvers
- supported currencies
- route metadata
- UI labels and icons
- schema versions

Important distinction:

```text
Application configuration
    Defines available behavior.

User preferences
    Define how one user configured that behavior.
```

Example:

```text
Application configuration:
    Planning is a supported navigation group.

User preferences:
    Planning is collapsed by default.
```

---

## 2.3 Registry Pattern

A registry is a central definition of supported entities or UI elements.

Registries are useful for:

- navigation
- data files
- features
- account types
- page metadata
- permissions
- cache invalidation tags

Example navigation registry:

```text
Navigation
├── Group
│   ├── Page
│   ├── Page
│   └── Subgroup
│       ├── Page
│       └── Page
```

A navigation entry should normally define:

- stable identifier
- visible label
- icon
- route endpoint
- related endpoints
- default order
- whether account scope is preserved
- whether the page is visible by default
- required permissions or feature flags

User preferences should store only overrides:

- hidden entries
- custom ordering
- collapsed groups
- collapsed subgroups

Do not duplicate the navigation structure in multiple templates.

---

# 3. Domain Layer

The domain layer defines the vocabulary and schemas of the application.

Examples:

- transaction
- account
- project
- task
- user
- document
- category
- recurring rule
- deadline
- notification
- payment method
- ledger movement

Typical contents:

- field definitions
- constants
- enums
- stable identifiers
- schema helpers
- validation primitives
- domain-level utility functions

The domain layer should not depend on:

- Flask
- HTML
- CSS
- JavaScript
- filesystem locations
- database connection details
- presentation formatting

The domain layer answers:

```text
What is this object?
What fields does it have?
What values are valid?
```

It should not answer:

```text
How is it displayed?
Where is it stored?
Which page renders it?
```

---

# 4. Repository Layer

Repositories are the persistence boundary.

Responsibilities:

- load records
- create records
- update records
- delete or archive records
- assign stable identifiers
- normalize legacy schemas
- map stored data to predictable structures
- perform atomic writes
- support yearly partitions
- manage migration compatibility
- expose query-oriented read functions

Repositories should not implement high-level business policy.

A repository may decide:

```text
How to load a transaction.
How to save a transaction.
Which yearly partition contains it.
How to move it between partitions.
```

A repository should not decide:

```text
Whether an account can be closed.
Whether a transaction should affect net balance.
Whether recurring rules must be changed.
```

Those decisions belong to services.

---

## 4.1 Repository Organization

Repositories can be grouped by entity or feature.

Entity-oriented example:

```text
repositories
├── transactions
├── accounts
├── internal transfers
├── recurring rules
├── debts
├── documents
└── shared persistence helpers
```

Feature-oriented example:

```text
features
├── transactions
│   ├── repository
│   ├── service
│   ├── routes
│   └── schemas
├── accounts
├── planning
└── documents
```

Use shared repository helpers for:

- CSV parsing
- JSON parsing
- schema normalization
- encryption-aware reads
- atomic writes
- file locking
- yearly partition discovery
- summary-index rebuilding

Avoid implementing these behaviors independently in each feature.

---

# 5. Service Layer

The service layer contains business logic.

Responsibilities:

- validation
- calculations
- workflow orchestration
- account routing
- transaction rules
- recurring logic
- pending logic
- account closure
- notifications
- reconciliation
- dashboard aggregation
- profile updates
- navigation customization
- migration workflows
- cache invalidation

A service may combine multiple repositories.

Example account-closure workflow:

```text
Close account
├── load account
├── verify account can be closed
├── inspect recurring rules
├── inspect payment methods
├── inspect debts and pending movements
├── verify remaining balance
├── create liquidation or transfer movement
├── mark account inactive
└── invalidate affected caches
```

Services should be callable independently from HTML rendering.

This allows reuse by:

- desktop pages
- phone pages
- API endpoints
- automation jobs
- tests
- command-line tools

---

## 5.1 Service Categories

### Entity Services

Operate mainly on one entity.

Examples:

- account service
- transaction service
- category service
- profile service
- project service
- task service

### Workflow Services

Coordinate several entities.

Examples:

- account closure
- internal transfer
- recurring generation
- statement settlement
- reconciliation
- import or migration
- bulk update

### Read-Model Services

Prepare data for screens.

Examples:

- dashboard overview
- account summary
- notification context
- net explanation
- top-bar summary
- analytics overview

### Infrastructure-Facing Services

Manage application behavior rather than domain entities.

Examples:

- cache service
- backup service
- export service
- navigation preferences
- security audit
- migration status

---

# 6. Web Layer

The web layer translates HTTP requests into service calls.

Conceptual structure:

```text
web
├── routes or controllers
├── templates
├── authentication
├── shared template context
└── error handling
```

---

## 6.1 Routes and Controllers

Route responsibilities:

1. read path parameters
2. read query parameters
3. read form or JSON payloads
4. validate basic request shape
5. call a service
6. handle expected errors
7. redirect or render a template

Routes should remain thin.

Recommended shape:

```python
def page():
    request_data = parse_request()
    context = feature_service.build_context(request_data)
    return render_template("feature/page.html", **context)
```

Avoid:

- large calculations inside routes
- direct encrypted file access
- complex validation inside templates
- repeated repository access from multiple route branches

---

## 6.2 Route Grouping

Routes should be grouped by business area.

Example:

```text
routes
├── core
│   ├── dashboard
│   ├── transactions
│   ├── analysis
│   └── summaries
├── accounts
│   ├── account overview
│   ├── account details
│   ├── reconciliation
│   └── internal transfers
├── planning
│   ├── pending
│   ├── recurring
│   ├── calendar
│   ├── goals
│   └── projects
├── assets
│   ├── investments
│   └── asset movements
├── records
│   ├── debts
│   ├── receivables
│   └── documents
└── settings
    ├── profile
    ├── preferences
    ├── categories
    ├── security
    ├── cache controls
    └── backups
```

This prevents a single routes directory from becoming unmanageable.

---

# 7. Template Structure

Templates are server-rendered and divided into three levels.

## 7.1 Base Shell

The base template defines:

- global page structure
- sidebar
- top bar
- profile block
- account and scope controls
- theme controls
- notifications
- main content area
- global CSS
- global JavaScript
- reusable dialogs

Every standard page extends this shell.

---

## 7.2 Shared Components

Use components for repeated markup.

Examples:

- scope selector
- account selector
- summary card
- transaction table
- filter toolbar
- empty state
- confirmation dialog
- custom-category dialog
- period selector
- navigation group
- pagination controls

A component is appropriate when:

- markup is reused
- behavior is reused
- styling is reused
- the component has stable inputs

Avoid copying the same selector, card, dialog, or toolbar into multiple pages.

---

## 7.3 Feature Templates

Feature templates contain only page-specific content.

Template grouping should mirror route grouping.

Example:

```text
templates
├── base shell
├── components
├── core
├── accounts
├── planning
├── assets
├── records
└── settings
```

Mirroring routes and templates makes features easier to locate.

---

# 8. Shared Template Context

Some values are required across most pages.

Examples:

- authenticated user
- profile display data
- active route
- navigation registry
- selected account
- selected scope
- formatting helpers
- theme state
- notification count
- top-bar data

These values can be injected through shared context processors.

Important performance rule:

```text
Do not run expensive business calculations in global context processors.
```

Prefer:

```text
Initial render:
    inject lightweight shell data

After render or through cached service:
    load expensive top-bar summaries
```

Otherwise every page pays the cost of dashboard calculations.

---

# 9. Frontend Organization

The frontend should be separated into:

```text
Frontend
├── design tokens
├── application shell
├── shared components
├── page-specific styles
├── shared JavaScript
├── page-specific JavaScript
└── platform-specific behavior
```

---

## 9.1 Design Tokens

Design tokens define:

- colors
- spacing
- border radii
- shadows
- typography
- animation durations
- z-index layers
- breakpoints

They should be reusable CSS custom properties.

Example:

```css
:root {
  --surface-primary: ...;
  --surface-secondary: ...;
  --text-primary: ...;
  --text-muted: ...;
  --border-soft: ...;
  --radius-card: ...;
  --space-md: ...;
}
```

---

## 9.2 Shared CSS

Shared CSS contains reusable UI primitives:

- buttons
- cards
- forms
- tables
- badges
- dialogs
- navigation
- floating submit controls
- loading states
- transitions

---

## 9.3 Page CSS

Complex pages should have dedicated styles.

Examples:

```text
pages
├── dashboard
├── transactions
├── accounts
├── profile
├── planning
└── analysis
```

Page CSS should not redefine the entire shell.

---

## 9.4 Platform-Specific CSS

Desktop and phone layouts may share services and templates while using separate presentation rules.

Separate platform-specific concerns such as:

- mobile bottom navigation
- desktop sidebar
- touch targets
- fixed headers
- viewport-safe spacing
- mobile dialogs
- desktop hover behavior

---

## 9.5 JavaScript Organization

Recommended grouping:

```text
JavaScript
├── shared application behavior
├── navigation
├── theme behavior
├── shared form behavior
├── page-specific behavior
├── phone-specific behavior
└── third-party libraries
```

Shared JavaScript examples:

- navigation acceleration
- theme switching
- notifications
- modal handling
- floating submit buttons
- shared form validation

Page JavaScript examples:

- dashboard period selector
- transaction editing
- drag-and-drop tasks
- chart controls
- account reconciliation

---

# 10. Security and Storage

Separate logical persistence from physical encrypted storage.

Recommended flow:

```text
Service
    ↓
Repository
    ↓
Secure storage API
    ↓
Encrypted data on disk
```

The secure storage layer handles:

- encryption
- decryption
- key management
- encrypted-file detection
- atomic encrypted writes
- secure deletion
- temporary decrypted exports
- schema migration
- integrity checks
- CRLF and LF compatibility

Repositories should not implement encryption details directly.

---

# 11. Runtime User Data

Runtime data should be conceptually separate from application source code.

Per-user structure:

```text
user data
├── profile and preferences
├── accounts and payment methods
├── transaction histories
├── planning data
├── documents
├── generated reports
├── backups
└── temporary or cache data
```

Each user should have an isolated data boundary.

---

## 11.1 Small Configuration Files

Use single files for data that remains small.

Examples:

- profile
- preferences
- categories
- navigation preferences
- account definitions
- payment methods
- recurring-rule definitions
- application settings

---

## 11.2 Growing Movement Histories

Use yearly partitions for append-heavy datasets.

Conceptual structure:

```text
movement type
├── movement_2025
├── movement_2026
├── movement_2027
└── summary index
```

Examples:

- expenses
- incomes
- investments
- internal transfers
- ledger movements
- audit events
- activity logs

Authoritative rule:

```text
Yearly records are authoritative.
Summary files are rebuildable caches.
```

The summary may contain:

- row count
- first timestamp
- last timestamp
- yearly total
- opening cumulative value
- closing cumulative value
- per-account totals
- content fingerprint
- schema version

---

## 11.3 Data Registry

Maintain one central registry for persistent datasets.

Each registry entry may define:

- logical name
- physical location
- file or directory type
- format
- schema
- sensitivity
- encryption requirement
- partitioning strategy
- backup policy
- cache tags
- migration version

This prevents:

- hard-coded file lists
- inconsistent backup behavior
- inconsistent encryption behavior
- duplicated migration rules

---

# 12. Caching and Performance

Use several cache layers with different lifetimes.

## 12.1 Request Cache

Lifetime:

```text
One HTTP request
```

Purpose:

- reuse repeated file reads
- reuse repeated calculations
- avoid decrypting the same file multiple times during one render

---

## 12.2 Process Cache

Lifetime:

```text
Until application restart or invalidation
```

Purpose:

- reuse stable computed values
- reuse parsed configuration
- reuse navigation metadata
- reuse account summaries

---

## 12.3 File-Read Cache

Purpose:

- avoid repeatedly decrypting and parsing unchanged files

Recommended cache key:

```text
user
+ logical file identity
+ content fingerprint or modification metadata
+ schema version
```

---

## 12.4 Calculation Cache

Purpose:

- store expensive derived values

Examples:

- account totals
- dashboard context
- analytics
- notification context
- top-bar summaries
- yearly rollups

---

## 12.5 Rendered-Page Cache

Purpose:

- accelerate server-rendered page transitions

Rules:

- do not perform duplicate warm-up and navigation requests
- do not block a real click while prefetch finishes
- do not aggressively prefetch every route
- invalidate after writes
- preserve browser history behavior
- avoid caching pages containing stale security-sensitive data

---

## 12.6 Selective Cache Invalidation

Every write should invalidate only affected cache groups.

Example:

```text
Save transaction
├── invalidate transaction list
├── invalidate affected account balances
├── invalidate dashboard
├── invalidate analysis
└── preserve unrelated profile and document caches
```

Avoid clearing every cache after every write.

---

# 13. Request Lifecycle

## 13.1 Read Request

```text
Browser requests page
        ↓
Request hooks initialize user context
        ↓
Authentication is checked
        ↓
Request cache is initialized
        ↓
Route parses parameters
        ↓
Service applies business rules
        ↓
Repository loads data
        ↓
Storage layer decrypts data if required
        ↓
Cache reuses or stores results
        ↓
Service builds template context
        ↓
Template extends the base shell
        ↓
HTML is returned
        ↓
JavaScript enhances interactions
```

---

## 13.2 Write Request

```text
Form or API submission
        ↓
Route validates request shape
        ↓
Service validates business rules
        ↓
Repositories perform atomic writes
        ↓
Yearly summaries are updated
        ↓
Affected caches are invalidated
        ↓
User is redirected or receives JSON
```

---

# 14. Feature Composition

A complete feature normally includes:

```text
Feature
├── domain schema
├── configuration or registry entry
├── repository
├── service
├── route
├── template
├── page CSS
├── page JavaScript
├── cache rules
└── tests
```

Example task-management feature:

```text
Task feature
├── Domain
│   ├── task fields
│   ├── statuses
│   └── priority values
├── Repository
│   ├── create
│   ├── read
│   ├── update
│   └── archive
├── Service
│   ├── assignment rules
│   ├── deadline rules
│   ├── completion logic
│   └── notifications
├── Routes
│   ├── list
│   ├── create
│   ├── detail
│   └── update
├── Templates
│   ├── list page
│   ├── detail page
│   └── editor component
├── Frontend
│   ├── task styles
│   └── drag-and-drop behavior
└── Cache
    └── invalidate project and dashboard summaries
```

---

# 15. Recommended Generic Directory Model

```text
application/
├── bootstrap/
├── config/
│   ├── defaults/
│   ├── registries/
│   └── paths/
├── domain/
│   ├── schemas/
│   ├── constants/
│   └── identifiers/
├── repositories/
│   ├── shared/
│   └── entity-specific/
├── services/
│   ├── entities/
│   ├── workflows/
│   └── read_models/
├── storage/
├── security/
├── cache/
├── performance/
├── validation/
├── web/
│   ├── routes/
│   │   ├── core/
│   │   ├── primary_business_area/
│   │   ├── planning/
│   │   ├── reporting/
│   │   └── settings/
│   ├── templates/
│   │   ├── components/
│   │   └── feature_groups/
│   ├── authentication/
│   ├── context/
│   └── errors/
└── frontend/
    ├── design_tokens/
    ├── shared_styles/
    ├── page_styles/
    ├── shared_scripts/
    ├── page_scripts/
    └── platform_specific/
```

---

# 16. Feature-Oriented Alternative

For a larger application, group implementation by feature.

```text
application/
├── core/
│   ├── bootstrap
│   ├── configuration
│   ├── security
│   ├── storage
│   └── caching
├── features/
│   ├── accounts/
│   │   ├── domain
│   │   ├── repository
│   │   ├── service
│   │   ├── routes
│   │   ├── templates
│   │   ├── frontend
│   │   └── tests
│   ├── transactions/
│   ├── planning/
│   ├── documents/
│   └── analytics/
└── shared/
    ├── UI components
    ├── validators
    ├── formatting
    └── utilities
```

This structure is preferable when:

- the service directory becomes too large
- multiple teams work on separate features
- features have independent schemas
- features require isolated tests
- feature ownership matters

---

# 17. AI Agent Implementation Rules

An AI coding agent working in this structure should follow these rules.

## Rule 1: Inspect Before Editing

Before making changes:

1. identify the feature
2. locate its route
3. locate its service
4. locate its repository
5. locate its template
6. locate its CSS and JavaScript
7. identify cache invalidation behavior
8. identify shared components involved

Do not patch only the visible template if the issue originates in a service or repository.

---

## Rule 2: Preserve Layer Boundaries

Do not:

- read files directly from routes
- calculate business values in templates
- implement encryption in repositories
- place navigation definitions in page templates
- duplicate shared components
- store derived summaries as authoritative data

---

## Rule 3: Prefer Minimal Changes

When fixing a bug:

- preserve existing public interfaces
- modify the smallest responsible layer
- avoid unrelated redesigns
- keep legacy compatibility where necessary
- add migration logic instead of deleting data

---

## Rule 4: Use Stable Identifiers

Use stable IDs for:

- users
- accounts
- transactions
- navigation pages
- categories
- projects
- tasks

Do not use visible labels as identifiers.

Labels can change.
IDs should remain stable.

---

## Rule 5: Treat Derived Data as Rebuildable

Examples of derived data:

- summaries
- charts
- cached totals
- indexes
- dashboard contexts
- generated reports

Derived data must be rebuildable from authoritative records.

---

## Rule 6: Invalidate Selectively

After a write:

- invalidate only related cache tags
- avoid clearing all caches
- force refresh only where correctness requires it

---

## Rule 7: Preserve Atomicity

For multi-step writes:

1. validate first
2. prepare all changes
3. write atomically where possible
4. update summaries
5. invalidate caches
6. report partial failure clearly

Never silently leave half-completed migrations.

---

## Rule 8: Separate Global and Scoped Context

Always distinguish:

- global application scope
- current account or project scope
- temporary page filters
- persistent user preferences

A temporary dashboard filter should not silently change global application state.

---

# 18. Common Anti-Patterns

Avoid these patterns.

## Fat Routes

Problem:

```text
Route parses data, calculates totals, reads files, writes files, and renders HTML.
```

Correction:

```text
Route delegates to services.
```

---

## Business Logic in Templates

Problem:

```text
Template decides whether a transaction affects balance.
```

Correction:

```text
Service computes the value before rendering.
```

---

## Direct File Access from Multiple Layers

Problem:

```text
Routes, services, and templates all open the same data file.
```

Correction:

```text
Repositories own persistence.
```

---

## Duplicate UI Definitions

Problem:

```text
Account selector copied into several pages.
```

Correction:

```text
Use one shared component.
```

---

## Global Cache Clearing

Problem:

```text
Every write clears every cache.
```

Correction:

```text
Invalidate affected tags only.
```

---

## Summary as Source of Truth

Problem:

```text
Historical totals exist only in a summary file.
```

Correction:

```text
Yearly records remain authoritative.
Summary is rebuildable.
```

---

## Endless CSS Overrides

Problem:

```text
New redesign rules are continuously appended after old rules.
```

Correction:

```text
Each selector has one owner.
Replace obsolete rules instead of stacking overrides.
```

---

# 19. Recommended Testing Strategy

## Unit Tests

Test:

- domain validators
- service calculations
- repository normalization
- yearly partition selection
- summary rebuilding
- cache invalidation rules

## Integration Tests

Test:

- route to service flow
- encrypted read and write behavior
- account closure workflow
- migration workflow
- transaction movement between years
- user isolation

## UI Tests

Test:

- shared navigation
- scope switching
- conditional controls
- modal behavior
- browser back and forward
- responsive layouts
- page transitions

## Data Integrity Tests

Test:

- duplicate IDs
- malformed rows
- missing yearly files
- stale summaries
- interrupted writes
- legacy schemas
- encrypted-file line endings

---

# 20. Recommended Development Workflow

For every new feature:

1. define domain schema
2. register configuration
3. create repository interface
4. implement service rules
5. define cache tags
6. create routes
7. create reusable components
8. create page templates
9. add page CSS
10. add page JavaScript
11. add tests
12. document migration requirements
13. validate mobile and desktop behavior

For every bug:

1. reproduce the issue
2. identify the responsible layer
3. inspect authoritative data
4. inspect derived data and caches
5. patch the smallest responsible layer
6. add regression tests
7. validate unrelated features remain unchanged

---

# 21. Core Architectural Principles

1. Keep routes thin.
2. Put business logic in services.
3. Keep persistence inside repositories.
4. Keep encryption inside the storage layer.
5. Mirror feature groups across routes and templates.
6. Use shared components for repeated UI.
7. Centralize registries.
8. Separate authoritative data from caches.
9. Isolate user data.
10. Use stable identifiers.
11. Invalidate caches selectively.
12. Keep desktop and mobile presentation separable.
13. Treat migrations as resumable workflows.
14. Avoid duplicate requests during navigation.
15. Replace obsolete CSS instead of layering overrides.
16. Make summaries and generated outputs rebuildable.
17. Preserve browser history semantics.
18. Keep temporary filters separate from persistent scope.
19. Validate before writing.
20. Prefer atomic and reversible changes.
