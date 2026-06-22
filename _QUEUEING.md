# QUEUEING





\--------------------------------------------------------------------------------------------



##### Prompt 6 — i18n infrastructure for English/Italian app shell





You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-5 are already completed:

\- Launcher exists.

\- Multi-user auth and user-specific data paths exist.

\- Profile/preferences exist.

\- Profile page includes language setting stored in preferences.json.

\- Custom categories/accounts exist.



Goal of this patch:

Add a scalable language/i18n system for English and Italian. For now translate the app shell, auth pages, profile/settings pages, sidebar/nav, common buttons, and main page headings where easy. Do not try to translate every single historical table label if it would make the patch too risky.



Implement the following:



1\. Add i18n files

Create:

\- money\_manager/i18n/en.json

\- money\_manager/i18n/it.json

\- money\_manager/services/i18n\_service.py



Use key-based translations:

{

&#x20; "nav.overview": "Overview",

&#x20; "nav.quick\_overview": "Quick overview",

&#x20; "nav.detailed\_overview": "Detailed overview",

&#x20; "nav.dashboard": "Dashboard",

&#x20; "nav.transactions": "Transactions",

&#x20; "nav.why\_this\_net": "Why this net?",

&#x20; "nav.planning": "Planning",

&#x20; "nav.accounts": "Accounts",

&#x20; "nav.analysis\_wealth": "Analysis \& wealth",

&#x20; "profile.title": "Profile",

&#x20; "common.save": "Save",

&#x20; "common.cancel": "Cancel",

&#x20; ...

}



Italian examples:

{

&#x20; "nav.overview": "Panoramica",

&#x20; "nav.quick\_overview": "Panoramica rapida",

&#x20; "nav.detailed\_overview": "Panoramica dettagliata",

&#x20; "nav.dashboard": "Dashboard",

&#x20; "nav.transactions": "Transazioni",

&#x20; "nav.why\_this\_net": "Perché questo netto?",

&#x20; "nav.planning": "Pianificazione",

&#x20; "nav.accounts": "Conti",

&#x20; "nav.analysis\_wealth": "Analisi e patrimonio",

&#x20; "profile.title": "Profilo",

&#x20; "common.save": "Salva",

&#x20; "common.cancel": "Annulla",

&#x20; ...

}



2\. i18n service

i18n\_service.py should:

\- Load selected language from current user preferences.

\- Fallback to English if missing.

\- Fallback to the key itself if translation missing.

\- Cache translation files safely but reload gracefully if missing.

\- Provide t(key, \*\*kwargs) function.

\- Support simple string formatting placeholders.



3\. Jinja integration

Update money\_manager/web/context.py:

\- Inject t into templates.

\- Inject current\_language.

\- Inject available\_languages:

&#x20; - en: English

&#x20; - it: Italiano



Then templates can use:

{{ t("nav.overview") }}



4\. Translate app shell first

Update:

\- money\_manager/web/templates/base.html

\- auth/login.html

\- auth/register.html

\- profile/profile.html

\- any settings/category/account management UI added in Step 5

\- Common button labels and nav labels



Important:

Do not break routes/endpoints. Only labels change.



5\. Make it scalable

Do not hardcode language-specific if/else in templates.

Use translation keys.

Make adding future languages simple:

\- Add new JSON file.

\- Add option in available\_languages.



6\. Profile language selector

Update Profile page language selector to use available\_languages.

Changing language should save preferences.json and reflect after refresh.



7\. Do not translate user-generated content

Do not translate:

\- User category names

\- User account names

\- Contact names

\- Transaction descriptions



8\. Styling

No redesign.

No phone-specific changes.



Validation requirements:

\- Run python -m compileall money\_manager.

\- Verify default language is English.

\- Change language to Italian in Profile.

\- Verify sidebar/nav/auth/profile/common buttons change language.

\- Verify missing keys do not crash app.

\- Verify user-generated category/account names remain unchanged.

\- Verify multi-user separation: user A can use Italian, user B can use English.

\- Existing pages still load.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- Translation key structure

\- What is translated now and what remains hardcoded for later





\--------------------------------------------------------------------------------------------



##### Prompt 7 — Contact registry





You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-6 are already completed:

\- Launcher exists.

\- Multi-user auth and user paths exist.

\- Profile/preferences exist.

\- Custom categories/accounts exist.

\- i18n infrastructure exists with English/Italian app shell.

\- contacts.json already exists per user from Step 3, but may be empty.



Goal of this patch:

Add a Contact Registry where the user can store people/company bank info for future bank-transfer-style transactions.



Important:

This patch only creates contacts and contact management. Do not implement Bonifico transaction flow yet; that comes in Step 8.



Implement the following:



1\. Contact service

Update/create:

\- money\_manager/services/contact\_service.py



Per-user file:

data/users/{user\_id}/contacts.json



Structure:

{

&#x20; "schema\_version": 1,

&#x20; "contacts": \[

&#x20;   {

&#x20;     "id": "uuid-or-safe-id",

&#x20;     "type": "person",

&#x20;     "first\_name": "",

&#x20;     "last\_name": "",

&#x20;     "company\_name": "",

&#x20;     "display\_name": "",

&#x20;     "relationship": "",

&#x20;     "iban": "",

&#x20;     "bic\_swift": "",

&#x20;     "bank\_name": "",

&#x20;     "email": "",

&#x20;     "phone": "",

&#x20;     "notes": "",

&#x20;     "is\_archived": false,

&#x20;     "created\_at": "",

&#x20;     "updated\_at": ""

&#x20;   }

&#x20; ]

}



Requirements:

\- Support person and company.

\- Generate stable unique contact IDs.

\- Search contacts by display name, first name, last name, company name, relationship, IBAN.

\- Archive instead of destructive delete by default.

\- Allow restore archived contact.

\- Mask IBAN in list views unless show\_sensitive\_data is enabled.

\- Validate/sanitize IBAN lightly:

&#x20; - Remove spaces for stored canonical version or store both raw/display.

&#x20; - Do not reject too aggressively because different countries exist.

\- Validate duplicate contacts softly:

&#x20; - Warn if same display name or same IBAN exists.

&#x20; - Do not silently overwrite.



2\. Contact routes

Create:

\- money\_manager/web/routes/contacts.py



Routes:

\- GET /contacts

\- GET /contacts/new

\- POST /contacts/new

\- GET /contacts/<contact\_id>

\- POST /contacts/<contact\_id>

\- POST /contacts/<contact\_id>/archive

\- POST /contacts/<contact\_id>/restore



All routes must require login and use current user only.



3\. Contact templates

Create:

\- money\_manager/web/templates/contacts/contacts.html

\- money\_manager/web/templates/contacts/contact\_form.html

\- money\_manager/web/templates/contacts/contact\_detail.html



Use existing app design.

Support:

\- Contact list with search

\- Add contact button

\- Edit contact

\- Archive/restore

\- Detail view

\- Empty state



4\. Navigation

Add Contacts to navigation/sidebar.

Place it logically near Accounts or Profile.

If Step 6 i18n exists, use translation keys:

\- nav.contacts

\- contacts.title

\- contacts.add\_contact

\- etc.



Add keys to en.json and it.json.



5\. Profile/settings link

Optionally add a card/link in Profile page:

\- Manage contacts



6\. Security/privacy

\- Do not expose contacts across users.

\- Do not serve contacts from static files.

\- Mask IBAN where appropriate.

\- Do not log sensitive contact data unnecessarily.



7\. Validation

\- Run python -m compileall money\_manager.

\- Verify /contacts requires login.

\- Verify creating a person contact works.

\- Verify creating a company contact works.

\- Verify editing works.

\- Verify archiving hides from active list but can be restored.

\- Verify search works.

\- Verify user A cannot see user B contacts.

\- Verify Italian/English labels work for the new contact pages.

\- Do not modify phone-specific UI.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- Contact JSON structure

\- How privacy/masking works





\--------------------------------------------------------------------------------------------



##### Prompt 8 — Bonifico flow connected to contacts





You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-7 are already completed:

\- Launcher exists.

\- Multi-user auth/user paths exist.

\- Profile/preferences exist.

\- Custom categories/accounts exist.

\- i18n infrastructure exists.

\- Contact registry exists and works.



Goal of this patch:

Add a “Bonifico” bank-transfer-style flow connected to contacts. This does NOT execute a real bank transfer. It only records the transfer/payment as a transaction in the Money Manager.



Important:

Do not integrate real banking APIs.

Do not claim the money was actually transferred.

The Bonifico flow should create a normal expense/internal transaction record with extra metadata.



Implement the following:



1\. Bonifico service

Create:

\- money\_manager/services/bonifico\_service.py



Responsibilities:

\- Validate selected source account.

\- Validate amount > 0.

\- Select existing contact OR create/suggest a new contact.

\- Create the corresponding transaction using existing transaction\_service/repository.

\- Store bonifico metadata safely.



2\. Data model

Extend transaction storage carefully.



Current transactions likely live in:

\- expenses.csv

\- incomes.csv

\- internal\_transfers.csv

or similar.



Add metadata fields only if safe:

\- payment\_method

\- contact\_id

\- contact\_name

\- iban\_snapshot

\- bic\_swift\_snapshot

\- bank\_name\_snapshot

\- transfer\_reference

\- transfer\_status



If CSV schema migration is needed:

\- Add missing columns automatically when reading/writing.

\- Do not break existing CSVs.

\- Existing rows should get empty values for new columns.

\- Old analytics should continue working.



For Bonifico:

\- payment\_method = "bonifico"

\- transfer\_status = "recorded"

\- Store iban\_snapshot so historical transaction keeps the old IBAN even if contact changes later.



3\. Routes

Create:

\- money\_manager/web/routes/bonifico.py



Routes:

\- GET /bonifico

\- POST /bonifico

\- GET /api/contacts/search?q=... maybe optional for autocomplete



All routes require login.



4\. Templates

Create:

\- money\_manager/web/templates/bonifico/bonifico.html



UI:

\- Select source account

\- Select existing contact with search/autocomplete

\- Or type recipient name manually

\- Amount

\- Date

\- Category

\- Description / reason / causale

\- IBAN/BIC fields if not using existing contact

\- Checkbox: “Save as new contact” when manually entering a new recipient

\- Submit button: “Record bonifico”

\- Clear warning text: “This records the payment in Money Manager. It does not execute a real bank transfer.”



5\. Contact integration

Behavior:

\- If existing contact is selected:

&#x20; - Fill display fields from contact.

&#x20; - Snapshot contact bank info into transaction metadata.

\- If manual recipient is typed and “Save as new contact” is checked:

&#x20; - Create a new contact using contact\_service.

&#x20; - Then create transaction linked to new contact.

\- If manual recipient is typed and not saved:

&#x20; - Create transaction with contact\_name only and no contact\_id.



6\. Navigation

Add Bonifico page to navigation.

Place near Transactions/Accounts or Contacts.

Add i18n keys to en.json and it.json:

\- nav.bonifico

\- bonifico.title

\- bonifico.record

\- bonifico.warning

\- etc.



7\. Transaction visibility

Update transaction detail/list pages if useful:

\- Show payment method if present.

\- Show linked contact name if present.

\- Show bonifico metadata in transaction detail.

\- Do not clutter transaction list too much.



8\. Validation

\- Run python -m compileall money\_manager.

\- Verify /bonifico requires login.

\- Verify recording bonifico to existing contact creates expense transaction.

\- Verify recording manual recipient without save creates transaction.

\- Verify manual recipient with save creates contact + transaction.

\- Verify transaction list/detail shows enough bonifico info.

\- Verify existing transaction imports/analytics are not broken by new columns.

\- Verify user A cannot use user B contacts.

\- Verify it does not change phone-specific UI.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- Exact transaction fields added

\- How contact snapshots work

\- Confirmation that this records only and does not execute real transfers









\--------------------------------------------------------------------------------------------



##### Prompt 9 — Customizable sidebar/page visibility/page order



You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-8 are already completed:

\- Launcher exists.

\- Multi-user auth/user paths exist.

\- Profile/preferences exist.

\- Custom categories/accounts exist.

\- i18n exists.

\- Contacts exist.

\- Bonifico flow exists.



Goal of this patch:

Make the desktop sidebar/navigation customizable per user:

\- Users can hide pages they do not care about.

\- Users can restore hidden pages.

\- Users can reorder pages inside groups.

\- Pages still exist even if hidden.

\- Hidden pages should be removed only from navigation, not from routing.



Important:

The screenshot shows grouped navigation like:

\- Overview

\- Planning

\- Accounts

\- Analysis \& wealth

The current base.html likely hardcodes this sidebar. Refactor it into a registry-driven system.



Implement the following:



1\. Navigation registry

Create:

\- money\_manager/config/navigation\_registry.py



Define all app pages in one central registry.



Example structure:

DEFAULT\_NAVIGATION = \[

&#x20; {

&#x20;   "group\_id": "overview",

&#x20;   "label\_key": "nav.overview",

&#x20;   "default\_open": true,

&#x20;   "default\_order": 10,

&#x20;   "items": \[

&#x20;     {

&#x20;       "page\_id": "quick\_overview",

&#x20;       "endpoint": "dashboard.overview\_simple",

&#x20;       "label\_key": "nav.quick\_overview",

&#x20;       "default\_visible": true,

&#x20;       "default\_order": 10

&#x20;     },

&#x20;     ...

&#x20;   ]

&#x20; },

&#x20; ...

]



Include all currently available pages:

\- Quick overview

\- Detailed overview

\- Dashboard

\- Transactions

\- Why this net?

\- Planning pages

\- Accounts

\- Currencies

\- Internal transfers

\- Investments

\- Analysis

\- Yearly summary

\- Contacts

\- Bonifico

\- Documents

\- Debts / Credits / Payables / Receivables / Parent support / Sparagnat if present



Use the correct Flask endpoint names from the actual repo.

Do not guess endpoint names without checking routes.



Documents page must be included in the navigation registry.



If document type management was added inside Documents, keep Documents visible by default.



Suggested placement:

\- Group: Accounts or Analysis \& wealth, depending on the current app structure

\- Better placement: Accounts / personal data area



The Documents page should be hideable from the sidebar, but direct URL access should still work.



2\. Navigation service

Update/create:

\- money\_manager/services/navigation\_service.py



Per-user file:

data/users/{user\_id}/navigation.json



Expected structure:

{

&#x20; "schema\_version": 1,

&#x20; "hidden\_pages": \[],

&#x20; "custom\_order": {

&#x20;   "overview": \["quick\_overview", "dashboard", "transactions"]

&#x20; },

&#x20; "group\_order": \["overview", "planning", "accounts", "analysis\_wealth"],

&#x20; "collapsed\_groups": \[]

}



Functions:

\- get\_effective\_navigation()

\- hide\_page(page\_id)

\- show\_page(page\_id)

\- move\_page(page\_id, direction or target index)

\- restore\_default\_navigation()

\- set\_group\_collapsed(group\_id, collapsed)

\- validate navigation config against registry

\- ignore unknown/deleted page IDs safely



3\. Refactor base.html

Update money\_manager/web/templates/base.html:

\- Remove hard-coded sidebar page list.

\- Render sidebar from effective navigation.

\- Use translation keys through t().

\- Highlight current page correctly.

\- Preserve the existing desktop visual style.

\- Do not focus on phone version for now.



4\. Navigation settings UI

Add a section in Profile page or a dedicated page:

\- “Customize navigation”

\- List groups and pages

\- Show/hide toggle for each page

\- Move up/down buttons

\- Restore defaults button

\- Optional group collapse defaults



Routes can be:

\- GET /profile/navigation

\- POST /profile/navigation/hide

\- POST /profile/navigation/show

\- POST /profile/navigation/move

\- POST /profile/navigation/restore



Or integrate into /profile if simpler.



5\. Safety rules

\- Do not allow hiding Profile page unless there is another obvious way to reach it.

\- Do not allow hiding Logout.

\- If a page is hidden, direct URL access should still work.

\- Unknown page IDs in navigation.json should not crash app.

\- New pages added in the registry should appear by default unless user explicitly hides them.



6\. i18n

Add missing translation keys to:

\- en.json

\- it.json



7\. Validation

\- Run python -m compileall money\_manager.

\- Verify sidebar renders from registry.

\- Verify all current pages still appear by default.

\- Verify hiding a page removes it from sidebar but direct URL still works.

\- Verify restoring defaults returns original sidebar.

\- Verify moving pages changes order and persists after refresh/logout/login.

\- Verify user A navigation customization does not affect user B.

\- Verify Italian/English sidebar labels still work.

\- Do not modify phone-specific behavior.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- Full navigation registry structure

\- How hidden/restored pages work





\--------------------------------------------------------------------------------------------



##### Prompt 10 — Backup/export/import, privacy mode, onboarding polish





You are given the latest ZIP of my Flask Money Manager repo.



Assume Steps 1-9 are already completed:

\- Launcher exists.

\- Multi-user auth/user paths exist.

\- Profile/preferences exist.

\- Custom categories/accounts exist.

\- i18n exists.

\- Contacts exist.

\- Bonifico exists.

\- Customizable sidebar exists.



Goal of this patch:

Add the final multi-user polish features:

1\. Per-user backup/export/import

2\. Privacy mode applied more consistently

3\. First-login onboarding wizard

4\. Data schema/version/migration helpers



Implement the following:



1\. Backup/export service

Create:

\- money\_manager/services/backup\_service.py

\- money\_manager/web/routes/backup.py

\- money\_manager/web/templates/profile/backup.html or integrate in Profile page



Features:

\- Export current user data as ZIP.

\- Include:

&#x20; - CSV files

&#x20; - JSON config files

&#x20; - contacts

&#x20; - profile/preferences/categories/accounts/navigation

&#x20; - documents if present

&#x20; - optional plots/cache excluded by default

\- Name export clearly:

&#x20; money\_manager\_backup\_{user\_id}\_{date}.zip

\- Do not include other users.

\- Do not include data/\_system/users.json.

\- Do not include password hashes.

\- Add export metadata:

&#x20; backup\_metadata.json with schema version, created\_at, app version if available.



Backup/export must include:

\- data/users/{user\_id}/documents/

\- data/users/{user\_id}/documents/\_metadata.json

\- data/users/{user\_id}/document\_types.json



Import/restore must:

\- Validate uploaded document paths.

\- Prevent path traversal inside document files.

\- Restore document metadata.

\- Restore document types.

\- Preserve uploaded documents.

\- Never import files outside the current user folder.



2\. Import/restore

Add import ZIP feature:

\- Upload backup ZIP.

\- Validate it is a Money Manager backup.

\- Validate no path traversal.

\- Restore only into current user’s folder.

\- Create automatic backup before importing.

\- Let user choose:

&#x20; - Replace current data

&#x20; - Merge where possible, if safe

For first implementation, replacement with pre-backup is acceptable.

\- Do not overwrite user auth/password.



3\. Privacy mode

Preferences already include:

\- privacy\_mode

\- show\_sensitive\_data



Make privacy mode more consistent:

\- Mask IBAN in profile/contact lists.

\- Mask bank details where appropriate.

\- Mask amounts in major dashboard/summary cards when privacy\_mode is true, unless show\_sensitive\_data is true.

\- Add a clear visual indicator when privacy mode is on.

\- Keep calculations unchanged; only display is masked.

\- Do not mask inside exported backups.



Use helper functions:

\- mask\_money(value)

\- mask\_iban(value)

\- mask\_text(value)

\- should\_mask\_sensitive()



4\. Onboarding wizard

Add first-login onboarding:

\- For a new user with incomplete profile/settings, redirect or suggest onboarding.

\- Do not trap the user forever; allow “Skip for now”.

\- Route:

&#x20; - GET /onboarding

&#x20; - POST /onboarding



Ask:

\- First name

\- Last name

\- Preferred language

\- Theme

\- Main currency

\- Main bank/account name

\- Optional initial balance

\- Default starting categories optional



If initial balance is provided:

\- Create/update main account initial balance safely according to existing account logic.

\- Do not create fake transaction unless current app architecture requires it.

\- If a transaction is needed, mark it as opening balance.



Set an onboarding\_completed flag in preferences.json.



5\. Schema/version helpers

Add:

\- money\_manager/services/schema\_service.py



Responsibilities:

\- Ensure user config files have schema\_version.

\- Add missing columns to CSVs safely.

\- Central place for future migrations.

\- Do not do destructive migrations.



6\. UI integration

Profile page should include:

\- Backup/export/import section

\- Privacy mode controls

\- Onboarding reset/reopen link maybe

\- Clear warning before import replacement



Navigation:

\- Add Backup/Settings link if needed, or keep inside Profile.

\- Use i18n keys in en.json and it.json.



7\. Validation

\- Run python -m compileall money\_manager.

\- Verify export creates ZIP with only current user data.

\- Verify export excludes password hashes and other users.

\- Verify import validates backup and restores current user data only.

\- Verify auto-backup before import is created.

\- Verify privacy mode masks dashboard/profile/contact sensitive info but does not alter data.

\- Verify onboarding appears for new user and can be skipped/completed.

\- Verify existing users are not forced into broken onboarding.

\- Verify multi-user isolation.

\- Do not modify phone-specific UI.

\- Verify exported backup includes uploaded documents.

\- Verify exported backup includes document\_types.json.

\- Verify import restores uploaded documents and metadata.

\- Verify imported documents are still downloadable from the Documents page.



Output:

Return the FULL updated repo as a downloadable .zip.

Also summarize:

\- Files added

\- Files modified

\- Backup ZIP structure

\- Import safety checks

\- Privacy mode behavior

\- Onboarding behavior



\--------------------------------------------------------------------------------------------





